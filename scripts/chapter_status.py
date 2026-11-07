# -*- coding: utf-8 -*-
"""chapter_status.py — 断点续传：这一章现在处于哪一步，下一条命令是什么。

只读脚本。依据产物是否存在、时间戳新旧以及 reports/chapter-checks.json 的哈希绑定判断阶段；
时间戳是启发式（复制文件会改变 mtime），遇到可疑状态时它宁可让你重跑上一步。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bt_common import StateError, read_json_strict, resolve_chapter_final, sha256_file, sha256_text  # noqa: E402
from p6_review import review_state  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def newer(a, b):
    return a.exists() and b.exists() and a.stat().st_mtime_ns >= b.stat().st_mtime_ns


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True, type=Path, help='章节目录，如 chapters/ch03')
    args = ap.parse_args(argv)
    ch = args.workspace.resolve()

    def cmd(name):
        """可直接粘贴执行的命令前缀：解释器与脚本路径各自独立加引号。"""
        return '"%s" "%s"' % (sys.executable, ROOT / name)

    book_root = ch.parent.parent if ch.parent.name == 'chapters' else ch
    strategy_path = book_root / 'runtime-strategy.json'
    result = {'chapter_dir': str(ch), 'runtime_strategy_path': str(strategy_path), 'sections': [], 'stage': None, 'next': None}

    def done(stage, nxt):
        result.update(stage=stage, next=nxt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        strategy = read_json_strict(strategy_path, default=None)
    except StateError as exc:
        return done('blocked', str(exc))
    if not isinstance(strategy, dict) or strategy.get('schema_version') != 1:
        result['runtime_mode'] = 'unknown'
        return done('host-probe', '先按 assets/runtime-strategy.template.json 探测宿主并写入 "%s"，再重新检查断点。' % strategy_path)
    if strategy.get('workspace') != str(book_root.resolve()):
        return done('host-probe', '策略文件记录的工作区与当前路径不符；核对后更新 "%s"。' % strategy_path)
    routing = strategy.get('routing')
    mode = routing.get('mode') if isinstance(routing, dict) else None
    if mode == 'unknown' or mode is None:
        result['runtime_mode'] = 'unknown'
        return done('host-probe', '在 "%s" 中选择有效的 A/B/C 路由后重新检查断点。' % strategy_path)
    if mode not in ('A', 'B', 'C'):
        return done('blocked', '策略路由值无效；保留 "%s" 并先核对文件内容。' % strategy_path)
    result['runtime_mode'] = mode
    host = strategy.get('host')
    capabilities = host.get('capabilities') if isinstance(host, dict) else None
    if not isinstance(capabilities, dict):
        return done('host-probe', '策略缺少 host.capabilities；重新探测并补全 "%s"。' % strategy_path)
    context_policy = host.get('context_policy')
    if not isinstance(context_policy, dict) or context_policy.get('kind') not in ('auto_compaction', 'hard_limit', 'stateless', 'unknown'):
        return done('host-probe', '策略中的上下文政策值无效；重新核验 "%s"。' % strategy_path)
    filesystem = capabilities.get('filesystem')
    subagent = capabilities.get('subagent')
    if not isinstance(filesystem, dict):
        filesystem = {}
    if not isinstance(subagent, dict):
        subagent = {}
    if mode == 'A' and not all(subagent.get(key) is True for key in
                               ('available', 'fresh_context', 'shared_workspace', 'permitted_for_task')):
        return done('host-probe', '策略选为 A，但子代理的新上下文或共享工作区能力未全部确认；重新探测后改选可用路由。')
    if mode == 'B' and not all((filesystem.get('read') is True, filesystem.get('write') is True,
                                capabilities.get('script_execution') is True)):
        return done('host-probe', '策略选为 B，但文件读写或脚本执行能力未全部确认；重新探测后改选可用路由。')

    if not (ch / 'outline.json').exists():
        return done('outline', '按 P1 生成 outline.md，再运行 %s --outline outline.md --numbered source-numbered.md --out-json outline.json' % cmd('check_outline.py'))
    try:
        outline = read_json_strict(ch / 'outline.json')
    except StateError as exc:
        return done('blocked', str(exc))
    if not (ch / 'term-plan.json').exists():
        return done('term-plan', '按 P1.5 生成 term-plan.json，再运行 %s --global-terms "%s/global-term-ledger.json" ...' % (cmd('check_term_plan.py'), book_root))
    sec = ch / 'sections'
    pending = []
    for s in outline.get('sections', []):
        k = s['k']
        p, u, t, r, f, c = (sec / n for n in ('%d-points.md' % k, '%d-teaching-units.json' % k, '%d-write-task.md' % k,
                                              '%d-revision.md' % k, '%d-final.md' % k, 'coverage-%d.md' % k))
        if not (p.exists() and u.exists()):
            stage, nxt = 'extract', '抽取：build_task_sheet --mode extract --k %d … 然后产出 points / teaching-units，并运行 run_stage_checks --stage extract --k %d' % (k, k)
        elif not t.exists() or not newer(t, p):
            stage, nxt = 'write-task', 'build_task_sheet.py --mode write --k %d …（points 比任务单新，或任务单不存在）' % k
        elif not r.exists() or not newer(r, t):
            if mode == 'A':
                nxt = '按模式 A 将 %d-write-task.md 与 P2H 提示交给新上下文写作者，要求直接写入 %d-revision.md；主 Agent 检查产物后续跑总控。' % (k, k)
            elif mode == 'B':
                nxt = '按模式 B 当前 Agent 只读取 %d-write-task.md 与 P2H 提示，写入 %d-revision.md 后续跑总控。' % (k, k)
            else:
                nxt = '按模式 C 生成本节有限交接卡；无工具宿主无法落盘时才交由用户迁移。目标产物为 %d-revision.md。' % k
            stage = 'write'
        elif not f.exists() or not newer(f, r):
            stage, nxt = 'validate', 'validate_revision.py --revision %d-revision.md --out %d-final.md，然后 run_stage_checks --stage draft --k %d' % (k, k, k)
        elif not c.exists() or not newer(c, f):
            stage, nxt = 'audit', '按 P8 产出 coverage-%d.md，然后 run_stage_checks --stage audit --k %d' % (k, k)
        else:
            stage, nxt = 'done', None
        result['sections'].append({'k': k, 'stage': stage, 'next': nxt})
        if stage != 'done':
            pending.append((k, stage, nxt))
    if pending:
        k, stage, nxt = pending[0]
        return done('section-%d:%s' % (k, stage), nxt)
    final, problems = resolve_chapter_final(ch)
    finals = [sec / ('%d-final.md' % s['k']) for s in outline.get('sections', [])]
    if problems and final is not None:
        return done('blocked', '; '.join(problems))
    if final is None or any(not newer(final, x) for x in finals):
        return done('merge', '%s --sections-dir sections --n %d --out chapter-final.md …（若有 P5 补丁，最终整章稿也写入 chapter-final.md）' % (cmd('merge_sections.py'), len(finals)))
    p6 = review_state(ch, final)
    quality = {'manual_p6': p6.get('status', 'missing'), 'punctuation_budget': 'not_run'}
    result['quality_gates'] = quality
    if p6.get('status') in ('missing', 'invalid', 'stale'):
        task_path = ch / 'reports' / 'p6-review-task.md'
        next_action = '%s --workspace "%s" --out "%s"; 按生成的任务先冷读中文定稿，再输出 reports/p6-review.md 与 reports/p6-review.json。' % (
            cmd('build_p6_task.py'), ch, task_path)
        return done('p6-review', next_action)
    if p6.get('status') == 'pending-revisions':
        return done('p9-patch', '按 prompts/P9-readability-patch.md 处理 P6 标为 revise/source_check 的项目，逐处回源并复核覆盖；更新 chapter-final.md 后重新执行 P6。')
    gate = ch / 'reports' / 'chapter-checks.json'
    try:
        report = read_json_strict(gate)
    except StateError as exc:
        return done('chapter-gate', str(exc))
    hashes = report.get('meta', {}).get('input_sha256', {}) if isinstance(report, dict) else {}
    inputs_current = bool(hashes) and all(Path(path).is_file() and hashes.get(path) == sha256_file(path) for path in hashes)
    check_results = {item.get('check'): item.get('result', {}) for item in report.get('checks', [])} if isinstance(report, dict) else {}
    punctuation = check_results.get('punctuation-budget')
    if inputs_current and isinstance(punctuation, dict):
        quality['punctuation_budget'] = 'passed' if punctuation.get('ok') is True else 'failed'
    if quality['punctuation_budget'] == 'failed':
        return done('p9-patch', '查看 reports/chapter-checks.json 中 punctuation-budget 的独立计数和超额位置；按 P9 做局部修订，保留译义，改后回源并重做 P6 与章节门禁。')
    manual_record = check_results.get('p6-manual-cold-read')
    has_new_checks = isinstance(manual_record, dict) and isinstance(punctuation, dict)
    if (not report or report.get('ok') is not True
            or report.get('meta', {}).get('final_sha256') != sha256_text(final.read_text(encoding='utf-8'))
            or not inputs_current or not has_new_checks):
        return done('chapter-gate', '%s --stage chapter --workspace "%s"' % (cmd('run_stage_checks.py'), ch))
    if not (ch / 'chapter-summary.json').exists():
        return done('summary', '根据 chapter-final.md 写 chapter-summary.json：{"conclusion": "...", "pending_questions": [...]}')
    return done('handover', '%s --workspace "%s" --chapter %s' % (cmd('generate_handover.py'), book_root, ch.name.replace('ch', '').lstrip('0') or '1'))


if __name__ == '__main__':
    sys.exit(main())
