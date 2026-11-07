"""Advance deterministic stages; return bounded, actionable work to the host Agent.

The host executes every returned agent action and calls this script again. This
module does not pretend a Python process can invoke arbitrary host model tools.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
from bt_common import StateError, read_json_strict, sha256_file, write_json_atomic
from workspace_config import load_config
from p6_review import review_state

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent

def digest(path):
    path = Path(path)
    if path.suffix.lower() in ('.md', '.json'):
        return sha256_file(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tracked_inputs(root, book):
    paths = [root / name for name in ('book.json', 'book-outline.md', 'book-continuity.json', 'global-term-ledger.json', 'book-config.json', 'config.json')]
    for ch in book['chapters']:
        directory = root / ch['dir']
        paths.extend(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.md', '.json'))
    return sorted({p.resolve() for p in paths if p.is_file()})

def command(name, *args):
    return [sys.executable, str(SCRIPTS / name), *map(str, args)]

def current(path, inputs):
    return path.is_file() and all(p.is_file() and path.stat().st_mtime_ns >= p.stat().st_mtime_ns for p in inputs)

def gate_current(path, inputs):
    if not path.is_file():
        return False
    report = read_json_strict(path)
    hashes = report.get('meta', {}).get('input_sha256', {})
    current_inputs = all(p.is_file() and hashes.get(str(p.resolve())) == digest(p) for p in inputs)
    if report.get('stage') == 'chapter':
        checks = {item.get('check'): item.get('result', {}) for item in report.get('checks', [])}
        if not all(checks.get(name, {}).get('ok') is True for name in ('p6-manual-cold-read', 'punctuation-budget')):
            return False
    return report.get('ok') is True and current_inputs

def runtime_strategy(root):
    path = root / 'runtime-strategy.json'
    if not path.is_file():
        return None
    data = read_json_strict(path, required=True)
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise StateError('unsupported or invalid runtime strategy at %s; preserve it and review before updating' % path)
    if data.get('workspace') != str(root.resolve()):
        raise StateError('runtime strategy workspace does not match %s; preserve it and review before updating' % root)
    routing = data.get('routing')
    if not isinstance(routing, dict):
        raise StateError('runtime strategy is missing routing at %s; preserve it and review before updating' % path)
    mode = routing.get('mode')
    if mode == 'unknown':
        return None
    if mode not in ('A', 'B', 'C'):
        raise StateError('runtime strategy has an invalid routing mode at %s; preserve it and review before updating' % path)
    host = data.get('host')
    capabilities = host.get('capabilities') if isinstance(host, dict) else None
    if not isinstance(capabilities, dict):
        raise StateError('runtime strategy is missing host capabilities at %s; preserve it and review before updating' % path)
    context_policy = host.get('context_policy')
    if not isinstance(context_policy, dict) or context_policy.get('kind') not in ('auto_compaction', 'hard_limit', 'stateless', 'unknown'):
        raise StateError('runtime strategy has an invalid context policy at %s; preserve it and review before updating' % path)
    filesystem = capabilities.get('filesystem')
    subagent = capabilities.get('subagent')
    if not isinstance(filesystem, dict):
        filesystem = {}
    if not isinstance(subagent, dict):
        subagent = {}
    if mode == 'A' and not all(subagent.get(key) is True for key in
                               ('available', 'fresh_context', 'shared_workspace', 'permitted_for_task')):
        raise StateError('runtime strategy selects A without all required subagent capabilities at %s; preserve it and review before updating' % path)
    if mode == 'B' and not all((filesystem.get('read') is True, filesystem.get('write') is True,
                                capabilities.get('script_execution') is True)):
        raise StateError('runtime strategy selects B without required disk or script capabilities at %s; preserve it and review before updating' % path)
    return data

def host_probe_action(root):
    strategy_path = root / 'runtime-strategy.json'
    template = SKILL / 'assets/runtime-strategy.template.json'
    return task('host-probe', 'host-prober',
                '探测当前会话实际可用的文件读写、脚本执行、子代理新上下文、共享工作区、现有 OCR 能力及语言，以及 Agent 能否开启新对话并在其中恢复工作区；只记录可见证据。根据模板记录 continuation.mode、handoff_trigger、handoff_materials 和面向用户的 user_summary，明确用户是否需要逐章或在上下文边界手动复制材料。不要把可安装能力当作现有能力，用户未同意前不得搜索、安装或运行新的 OCR 工具。上下文窗口或压缩策略未明确公开时写 unknown。按模板生成 runtime-strategy.json 并选择 A/B/C 路由，然后重新调用总控。',
                [template], [strategy_path])

def writer_route(strategy):
    mode = strategy['routing']['mode']
    if mode == 'A':
        return {'mode': mode, 'dispatch': 'fresh_context_subagent', 'prefer_fresh_context': True,
                'instructions': '按模式 A 委派全新上下文的独立写作者；只传列出的中文 inputs，并要求结果直接写入 expected_outputs。主 Agent 检查落盘产物后继续总控。'}
    if mode == 'B':
        return {'mode': mode, 'dispatch': 'current_agent_disk', 'prefer_fresh_context': False,
                'instructions': '按模式 B 由当前 Agent 使用磁盘任务单分阶段写作和核验；只读取当前动作所需文件，不在上下文累积旧章节全文。'}
    return {'mode': mode, 'dispatch': 'manual_handover', 'prefer_fresh_context': False,
            'instructions': '按模式 C 输出仅覆盖当前阶段的交接卡，列出最小材料、目标产物和下一动作；不得假设可读写工作区。'}

def annotate_runtime_action(action, root, strategy):
    if action.get('kind') != 'agent':
        return action
    action = dict(action)
    route = writer_route(strategy)
    host = strategy.get('host', {})
    policy = host.get('context_policy', {}) if isinstance(host, dict) else {}
    action['runtime_strategy_path'] = str(root / 'runtime-strategy.json')
    action['routing_mode'] = route['mode']
    action['context_policy'] = policy.get('kind', 'unknown') if isinstance(policy, dict) else 'unknown'
    action['host_dispatch'] = route['dispatch']
    action['prefer_fresh_context'] = route['prefer_fresh_context']
    if action.get('role') != 'writer':
        if route['mode'] == 'A':
            guidance = '按模式 A，可将此独立角色动作交给新上下文；只传本动作 inputs，并让产物直接写入 expected_outputs。主 Agent 检查后继续。'
        elif route['mode'] == 'B':
            guidance = '按模式 B 由当前 Agent 使用磁盘 inputs/expected_outputs 执行，避免在会话中累积历史全文。'
        else:
            guidance = '按模式 C 仅生成本阶段有限交接卡；无本地工具时才需要用户迁移内容。'
        action['instructions'] = action.get('instructions', '').rstrip() + ' ' + guidance
    return action

def task(stage, role, instructions, inputs=(), outputs=(), commands=(), prepare=(), **extra):
    return {'ok': True, 'all_done': False, 'stage': stage, 'kind': 'tool' if role == 'tool' else 'agent', 'role': role, 'instructions': instructions, 'inputs': list(map(str, inputs)), 'expected_outputs': list(map(str, outputs)), 'commands': list(commands), 'prepare_commands': list(prepare), **extra}

def tool(stage, *commands):
    return task(stage, 'tool', '执行以下确定性步骤；失败时按具体诊断修复。', commands=commands)

def layout_action(root, outputs):
    review = root / 'reports/delivery-layout.json'
    return task('layout-review', 'layout-editor', '自动更新 DOCX 目录和分页并逐页检查。Windows 可用装有 pywin32 的宿主 Python 运行 finalize_docx.py --docx <文件> --pdf <工作区内部预览.pdf>；主解释器缺包时自动使用宿主依赖运行时，无需用户安装。也可使用宿主的其他排版引擎。查看全部页面，修正截断、乱码、表格越界与目录问题后重新导出。完成后写 delivery-layout.json：ok:true、docx_sha256（最终文件的 SHA256）、reviewed_pages（实际检查页数）、unresolved_issues:[]。不把刷新目录或核对排版交给用户。', [outputs['docx_path'], SKILL / 'scripts/finalize_docx.py'], [review])

def check_action(ch, stage, k, inputs):
    report = ch / 'reports' / f'{stage}-{k}-checks.json'
    if gate_current(report, inputs):
        return None
    if report.exists():
        data = read_json_strict(report)
        hashes = data.get('meta', {}).get('input_sha256', {})
        if data.get('ok') is False and hashes and all(p.is_file() and hashes.get(str(p.resolve())) == digest(p) for p in inputs):
            return task(f'section-{k}:repair-{stage}', 'editor', '根据失败项修复输入或成稿。漏抽先回源重抽，改义修正限定与归属；风格提示无需回炉。修复后继续运行总控，不把内部问题交给用户。', [report, *inputs], diagnostics=data.get('checks', []))
    return tool(f'section-{k}:check-{stage}', command('run_stage_checks.py', '--stage', stage, '--workspace', ch, '--k', k, '--out-json', report))

def next_action(root, book, strategy):
    chapters = book.get('chapters', [])
    if not chapters:
        raise ValueError('book has no chapters')
    outline = root / 'book-outline.md'
    continuity_path = root / 'book-continuity.json'
    continuity = read_json_strict(continuity_path, default={})
    thesis = str(continuity.get('book_thesis', '') or '')
    thesis_placeholder = '（待在第1章或全书规划中具体提炼）' in thesis or '(待在第1章或全书规划中具体提炼)' in thesis
    if not outline.exists() or thesis_placeholder:
        reason = '；当前全书主旨仍是初始化占位，需据真实章节重建' if thesis_placeholder else ''
        return task('book-outline', 'planner', '读取目录和各章代表性正文，建立实际全书脉络；写 book-outline.md，更新 book-continuity.json 的 book_thesis 与 book_arc，并把确认后的书名、作者和源语言写回 book.json。不要保留初始化占位话。自动决定中文暂定书名和译名，继续处理全书。' + reason, [root / 'book.json', continuity_path, SKILL / 'prompts/P0-book-outline.md', *[root / c['dir'] / 'source-numbered.md' for c in chapters]], [outline, continuity_path, root / 'book.json'])
    for chapter in chapters:
        ch = root / chapter.get('dir', f"chapters/ch{chapter['id']:02d}")
        source, plan, terms = ch / 'source-numbered.md', ch / 'outline.json', ch / 'term-plan.json'
        final = ch / 'chapter-final.md'
        chapter_gate = ch / 'reports/chapter-checks.json'
        if chapter.get('status') == 'done' and final.exists() and chapter_gate.exists():
            gate = read_json_strict(chapter_gate)
            hashes = gate.get('meta', {}).get('input_sha256', {})
            if gate.get('ok') and gate.get('meta', {}).get('final_sha256') == digest(final) and (not hashes or all(Path(p).is_file() and digest(p) == value for p, value in hashes.items())):
                continue
        context = {'current_chapter': chapter['id'], 'chapter_dir': str(ch), 'source_lang': book.get('source_lang', 'en')}
        action = chapter_action(ch, root, source, plan, terms, final, chapter_gate, strategy)
        return {**action, **context}
    return task('deliver', 'tool', '全部章节完成，执行全书汇编与交付检查。', commands=[command('merge_book.py', '--workspace', root)])

def chapter_action(ch, root, source, plan, terms, final, chapter_gate, strategy):
    outline_md = ch / 'outline.md'
    if not plan.exists() or source.stat().st_mtime_ns > plan.stat().st_mtime_ns:
        if current(outline_md, [source]):
            return tool('outline-check', command('check_outline.py', '--outline', outline_md, '--numbered', source, '--out-json', plan))
        return task('outline', 'planner', '按 P1 建立本章完整大纲，不以提炼主旨代替全量论述。每个源段都有归属；标题和元数据由 Agent 判断。', [source, root / 'book-continuity.json', SKILL / 'prompts/P1-chapter-outline.md'], [outline_md])
    if not current(terms, [plan]):
        return task('term-plan', 'terminologist', '按 P1.5 生成本章术语计划，沿用台账，给出简明释义；仅在核心术语的译名确有疑问时使用可用搜索工具。查不到时根据语境决定并记录译注，无需用户审批。', [source, plan, root / 'global-term-ledger.json', SKILL / 'prompts/P1.5-term-plan.md'], [terms])
    records = read_json_strict(plan, required=True).get('sections', [])
    if not records:
        raise ValueError('outline has no sections')
    sections = ch / 'sections'
    finals = []
    for record in records:
        k = record['k']
        points, units, sheet, revision, section_final, audit = [sections / f'{k}-{name}' for name in ('points.md', 'teaching-units.json', 'write-task.md', 'revision.md', 'final.md', 'coverage-unused')]
        audit = sections / f'coverage-{k}.md'
        extract = sections / f'{k}-extract-task.md'
        base = [source, plan, terms]
        if not all(current(p, base) for p in (points, units)):
            before = [command('build_task_sheet.py', '--mode', 'extract', '--k', k, '--outline-json', plan, '--numbered', source, '--sections-dir', sections, '--template', SKILL / 'prompts/P3-extract-sheet.md', '--out', extract)]
            return task(f'section-{k}:extract', 'extractor', '读抽取任务单，按 P7/P2H-Units 产出全部实质意义项和讲解单元。保留例子、异议、回应及必要铺陈；纯导航或噪声可注明非承重。', [extract, terms, SKILL / 'prompts/P7-points.md', SKILL / 'prompts/P2H-teaching-units.md'], [points, units], prepare=before)
        check = check_action(ch, 'extract', k, [*base, points, units])
        if check:
            return check
        sheet_inputs = [plan, terms, points, units]
        if k > 1:
            sheet_inputs.append(sections / f'{k - 1}-final.md')
        if not current(sheet, sheet_inputs):
            return tool(f'section-{k}:write-task', command('build_task_sheet.py', '--mode', 'write', '--k', k, '--outline-json', plan, '--points', points, '--sections-dir', sections, '--template', SKILL / 'prompts/P3-write-sheet.md', '--leak-source', source, '--out', sheet))
        if not current(revision, [sheet]):
            route = writer_route(strategy)
            return task(f'section-{k}:write', 'writer',
                        '按中文任务单写完整研读正文，保留全部实质论述，用自然中文重组句段。必要补充单独标明。%s 按 P2H 格式输出。' % route['instructions'],
                        [sheet, SKILL / 'prompts/P2H-write.md', SKILL / 'prompts/P2H-expansion.md', SKILL / 'prompts/P2H-exemplars.md'],
                        [revision], prefer_fresh_context=route['prefer_fresh_context'],
                        routing_mode=route['mode'], writer_dispatch=route['dispatch'])
        if not current(section_final, [revision]):
            return tool(f'section-{k}:validate', command('validate_revision.py', '--revision', revision, '--out', section_final))
        check = check_action(ch, 'draft', k, [plan, terms, section_final])
        if check:
            return check
        if not current(audit, [points, section_final, source]):
            return task(f'section-{k}:audit', 'source-reviewer', '先逐段回读原文，再核意义项和成稿。按照 P8 产出覆盖及反查记录。漏抽、删减或改义先修清单/成稿再重核，不通过改报告掩盖问题。', [source, points, section_final, SKILL / 'prompts/P8-coverage.md'], [audit])
        check = check_action(ch, 'audit', k, [*base, points, section_final, audit])
        if check:
            return check
        finals.append(section_final)
    marked, p5 = ch / 'merged-draft-marked.md', ch / 'p5-task.md'
    if not current(final, finals) or not marked.exists():
        return tool('merge', command('merge_sections.py', '--sections-dir', sections, '--n', len(records), '--out', final, '--out-marked', marked))
    if not current(p5, [marked, terms]):
        return tool('p5-task', command('build_p5_task.py', '--workspace', ch, '--out', p5))
    review = ch / 'p5-review.md'
    if not current(review, [marked, p5]):
        return task('integrate', 'editor', '执行 P5 章节整合，必要时把补丁应用到 chapter-final.md，完成后写 p5-review.md。保留原作具有阅读功能的重复和铺陈；不制造补丁。改动影响证据时更新相应 coverage 并重新核验。', [p5, final], [review, final])
    p6_prompt = SKILL / 'prompts/P6-final-review.md'
    p6_task = ch / 'reports/p6-review-task.md'
    p6_json, p6_markdown = ch / 'reports/p6-review.json', ch / 'reports/p6-review.md'
    if not current(p6_task, [final, p6_prompt]):
        return tool('p6-task', command('build_p6_task.py', '--workspace', ch, '--out', p6_task))
    p6 = review_state(ch, final)
    if p6.get('status') in ('missing', 'invalid', 'stale'):
        return task('p6-review', 'source-reviewer',
                    '执行独立 P6 人工冷读。先只读冷读任务中的中文定稿并记录读感，再按需回源；不要把脚本候选清单逐条搬进报告。输出简明诊断 Markdown 和规定结构的 JSON；风格候选可说明理由后保留。',
                    [p6_task], [p6_markdown, p6_json], prefer_fresh_context=True)
    if p6.get('status') == 'pending-revisions':
        revision_inputs = [final, source, p6_markdown, p6_json, SKILL / 'prompts/P9-readability-patch.md']
        for record in records:
            k = record['k']
            revision_inputs.extend([sections / f'{k}-points.md', sections / f'coverage-{k}.md'])
        return task('p9-patch', 'editor',
                    '只处理 P6 JSON 中 action 为 revise/source_check 的项目，局部编辑 chapter-final.md 并写 reports/p9-review.md。每处回到源段核对否定范围、条件、让步、模态、观点归属；只复核受改动段落对应的覆盖证据。不得为标点计数删改译义；若存在不能安全处理的高风险问题，说明阻断原因。改动后总控会要求针对新版本重新执行 P6。',
                    revision_inputs, [final, ch / 'reports/p9-review.md'], prefer_fresh_context=True)
    if not gate_current(chapter_gate, [source, plan, terms, final, *finals]):
        if chapter_gate.exists():
            data = read_json_strict(chapter_gate)
            hashes = data.get('meta', {}).get('input_sha256', {})
            if data.get('ok') is False and hashes and all(Path(p).is_file() and digest(p) == value for p, value in hashes.items()):
                return task('repair-chapter', 'editor', '依据整章门禁修复失败项。标点预算超限或已确认的风格问题按 P9 做局部修订，超额位置仅作定位；实质删漏或改义回到对应 P7/P8 内容修正并更新审计。不得自动删标点或牺牲译义。改动后会使 P6 记录失效，须复核新版本。', [chapter_gate, final, source, SKILL / 'prompts/P9-readability-patch.md'], diagnostics=data.get('checks', []))
        return tool('chapter-gate', command('run_stage_checks.py', '--stage', 'chapter', '--workspace', ch))
    summary = ch / 'chapter-summary.json'
    if not current(summary, [final]):
        return task('summary', 'reader', '根据定稿记录实际结论和遗留问题，写 chapter-summary.json，字段 conclusion、pending_questions、title_zh。不要照抄计划结论，不制造悬念；title_zh 为自然中文章标题。', [final], [summary])
    return tool('handover', command('generate_handover.py', '--workspace', root, '--chapter', int(ch.name[2:])))

def execute(argv, cwd):
    result = subprocess.run(argv, cwd=str(cwd), env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, encoding='utf-8', errors='replace')
    raw = result.stdout.split('\n====', 1)[0].strip()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {'ok': False, 'stdout': result.stdout[-3000:], 'stderr': result.stderr[-2000:]}
    if result.returncode or data.get('ok') is False:
        return {'ok': False, 'command': argv, 'diagnostic': data, 'stderr': result.stderr[-2000:]}
    return {'ok': True, 'result': data}

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', '-w', required=True, type=Path)
    parser.add_argument('--no-auto-merge', action='store_true')
    parser.add_argument('--describe', action='store_true', help='Return next action without advancing deterministic steps')
    args = parser.parse_args()
    root = args.workspace.resolve()
    try:
        for _ in range(20):
            book = read_json_strict(root / 'book.json', required=True)
            manifest = root / 'output/delivery-manifest.json'
            review = root / 'reports/delivery-layout.json'
            if manifest.is_file():
                saved = read_json_strict(manifest)
                hashes = saved.get('sha256', {})
                expected = {str(p) for p in tracked_inputs(root, book)} | set(saved.get('deliverables', {}).values()) | {str(review.resolve())}
                if hashes and set(hashes) == expected and all(Path(p).is_file() and digest(p) == value for p, value in hashes.items()):
                    print(json.dumps({'ok': True, 'all_done': True, 'stage': 'complete', 'deliverables': saved['deliverables']}, ensure_ascii=False, indent=2))
                    return 0
            pending = root / 'output/pending-layout.json'
            if pending.is_file():
                prepared = read_json_strict(pending)
                inputs = prepared.get('input_sha256', {})
                if set(inputs) == {str(p) for p in tracked_inputs(root, book)} and all(Path(p).is_file() and digest(p) == value for p, value in inputs.items()):
                    outputs = prepared['deliverables']
                    checked = read_json_strict(review, default={})
                    if checked.get('ok') is True and checked.get('reviewed_pages', 0) > 0 and checked.get('unresolved_issues') == [] and checked.get('docx_sha256') == digest(outputs['docx_path']):
                        tracked = [*tracked_inputs(root, book), *map(Path, outputs.values()), review]
                        write_json_atomic(manifest, {'deliverables': outputs, 'sha256': {str(p.resolve()): digest(p) for p in tracked}})
                        print(json.dumps({'ok': True, 'all_done': True, 'stage': 'complete', 'deliverables': outputs}, ensure_ascii=False, indent=2))
                        return 0
                    print(json.dumps(layout_action(root, outputs), ensure_ascii=False, indent=2))
                    return 0
            strategy = runtime_strategy(root)
            if strategy is None:
                print(json.dumps(host_probe_action(root), ensure_ascii=False, indent=2))
                return 0
            action = next_action(root, book, strategy)
            action = annotate_runtime_action(action, root, strategy)
            if action['kind'] == 'agent' and action['prepare_commands'] and not args.describe:
                for argv in action['prepare_commands']:
                    result = execute(argv, root)
                    if not result['ok']:
                        action = task(action['stage'] + ':repair', 'editor', '根据诊断修复输入，再调用总控继续。', action['inputs'], diagnostics=result)
                        break
                else:
                    action['prepare_commands'] = []
            if action['kind'] == 'agent' or args.describe or action['stage'] == 'deliver' and args.no_auto_merge:
                print(json.dumps(action, ensure_ascii=False, indent=2))
                return 0
            for argv in action['commands']:
                result = execute(argv, root)
                if not result['ok']:
                    print(json.dumps(task(action['stage'] + ':repair', 'editor', '修复诊断指出的实际问题后继续运行总控，不要求用户处理内部产物。', action['inputs'], diagnostics=result), ensure_ascii=False, indent=2))
                    return 0
            if action['stage'] == 'deliver':
                data = result['result']
                checked = execute(command('run_stage_checks.py', '--stage', 'deliver', '--workspace', root, '--docx', data['docx_path']), root)
                if not checked['ok']:
                    print(json.dumps(task('delivery-repair', 'editor', '修复交付问题后重新运行总控。', diagnostics=checked), ensure_ascii=False, indent=2))
                    return 0
                outputs = {key: data[key] for key in ('markdown_path', 'docx_path', 'glossary_path')}
                write_json_atomic(pending, {'deliverables': outputs, 'input_sha256': {str(p): digest(p) for p in tracked_inputs(root, book)}})
        raise ValueError('20 deterministic steps without an agent boundary; inspect workflow before repeating')
    except (OSError, ValueError, KeyError, StateError) as error:
        print(json.dumps({'ok': False, 'all_done': False, 'error': str(error)}, ensure_ascii=False))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
