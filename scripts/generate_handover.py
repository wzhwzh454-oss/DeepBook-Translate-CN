# -*- coding: utf-8 -*-
"""generate_handover.py — 跨章节上下文交接生成器 (v2.1, transactional).

v2.0 defects fixed here (all reproduced in the review):
  * a corrupt/truncated global-term-ledger.json was silently replaced by [] and then overwritten
    (40 locked terms -> 1)           -> strict reads, refuse to continue, .bak backups, atomic writes
  * term drift was only a stderr warning and the 2nd translation was appended as ANOTHER locked
    entry                           -> drift/ambiguity are hard errors, nothing is merged
  * chapters were marked done without any gate evidence -> require reports/chapter-checks.json
    (ok + sha256 of the current final text) unless --force
  * chapter-final.md silently beat a P5-patched merged-final.md -> resolve_chapter_final()
  * chapter-local term ids (T1) collided across chapters -> global uid c01:T1, depends_on rewritten
  * "上一章核心结论" was the outline's core *question* -> chapter-summary.json (agent-written) is
    preferred; outline fallback is labelled as such
  * handover prompt grew O(N) per chapter -> older chapters one-liners, big ledgers summarised
Write order is crash-safe: ledger -> continuity -> prompts -> book.json (progress pointer last).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bt_common import (StateError, merge_plan_into_ledger, read_json_strict,  # noqa: E402
                       resolve_chapter_final, sha256_text, write_json_atomic, write_text_atomic)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

LEDGER_FULL_TABLE_MAX = 80
TAIL_MAX_CHARS = 400


def split_paragraphs(text):
    return [b.strip() for b in re.split(r'\n\s*\n', text.strip()) if b.strip()]


def fail(message, code=1, **extra):
    print(json.dumps({'ok': False, 'error': message, **extra}, ensure_ascii=False, indent=2))
    sys.exit(code)


def main(argv=None):
    parser = argparse.ArgumentParser(description='生成下一章跨上下文交接 Prompt')
    parser.add_argument('--workspace', '-w', required=True, help='全书工作区绝对路径')
    parser.add_argument('--chapter', '-c', type=int, required=True, help='刚完成的章节编号 (k)')
    parser.add_argument('--force', action='store_true',
                        help='跳过「章节门禁 + 前序章节已完成」检查（记入账本 forced=true）')
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    try:
        book = read_json_strict(workspace / 'book.json', required=True)
        ledger = read_json_strict(workspace / 'global-term-ledger.json', default=[])
        continuity = read_json_strict(workspace / 'book-continuity.json',
                                      default={'book_thesis': '', 'book_arc': '', 'chapter_summaries': []})
    except StateError as exc:
        fail(str(exc))
    if isinstance(ledger, dict):
        ledger = ledger.get('terms', [])
    k = args.chapter
    total = book.get('total_chapters', 1)
    ch_dir = workspace / 'chapters' / ('ch%02d' % k)
    if not ch_dir.exists():
        fail('章节目录不存在: %s' % ch_dir)

    infos = {c['id']: c for c in book.get('chapters', [])}
    if not args.force:
        unfinished = [i for i in range(1, k) if infos.get(i, {}).get('status') != 'done']
        if unfinished:
            fail('前序章节尚未完成: %s（按顺序处理，或使用 --force）' % unfinished)

    final_file, problems = resolve_chapter_final(ch_dir)
    if problems:
        fail('; '.join(problems))
    final_text = final_file.read_text(encoding='utf-8')

    report_path = ch_dir / 'reports' / 'chapter-checks.json'
    if not args.force:
        try:
            gate = read_json_strict(report_path)
        except StateError as exc:
            fail(str(exc))
        if gate is None:
            fail('缺少章节门禁报告 %s；先运行 run_stage_checks.py --stage chapter' % report_path)
        if gate.get('ok') is not True:
            fail('章节门禁未通过（%s），不能固化术语/推进进度' % report_path)
        if gate.get('meta', {}).get('final_sha256') != sha256_text(final_text):
            fail('章节门禁报告已过期：定稿在检查之后被修改，请重新运行 --stage chapter')

    # ---- derive handover facts
    paras = [p for p in split_paragraphs(final_text) if not p.lstrip().startswith(('〔补充〕', '#', '<!--'))]
    tail = paras[-1] if paras else '无（本章文本为空）'
    if len(tail) > TAIL_MAX_CHARS:
        tail = '…' + tail[-TAIL_MAX_CHARS:]

    question, conclusion, pending, concl_source = '', '', [], 'outline-plan'
    outline = read_json_strict(ch_dir / 'outline.json', default={})
    if outline:
        question = outline.get('thesis', '')
        sections = outline.get('sections', [])
        if sections:
            last = sections[-1]
            conclusion = last.get('conclusion', '')
            if last.get('open_question') and last['open_question'] != '无':
                pending.append(last['open_question'])
    summary_file = ch_dir / 'chapter-summary.json'
    if summary_file.exists():
        try:
            written = read_json_strict(summary_file)
            conclusion = written.get('conclusion') or conclusion
            pending = written.get('pending_questions') or pending
            concl_source = 'chapter-summary.json'
        except StateError as exc:
            fail(str(exc))
    conclusion = conclusion or ('第 %d 章论证完成（详见定稿）' % k)
    pending = pending or ['承接第 %d 章的结论，推进全书下一阶段论证。' % k]

    # ---- terms: hard errors on drift/ambiguity, no partial merge
    plan = read_json_strict(ch_dir / 'term-plan.json', default=None)
    conflicts = []
    if plan:
        ledger, conflicts = merge_plan_into_ledger(ledger, plan.get('terms', []), k)
    if conflicts:
        fail('术语台账冲突，未写入任何状态', code=2, conflicts=conflicts)

    summary_entry = {'chapter': k, 'title': infos.get(k, {}).get('title', 'Chapter %d' % k),
                     'question': question, 'thesis': conclusion, 'conclusion_source': concl_source,
                     'ending_tail': tail, 'pending_questions': pending, 'forced': bool(args.force),
                     'final_sha256': sha256_text(final_text)}
    cs = continuity.setdefault('chapter_summaries', [])
    for i, old in enumerate(cs):
        if old.get('chapter') == k:
            cs[i] = summary_entry
            break
    else:
        cs.append(summary_entry)
    cs.sort(key=lambda s: s.get('chapter', 0))

    # ---- persist (ledger -> continuity); progress pointer last
    write_json_atomic(workspace / 'global-term-ledger.json', ledger)
    write_json_atomic(workspace / 'book-continuity.json', continuity)

    if k >= total:
        infos.get(k, {})['status'] = 'done'
        book['current_chapter'] = total
        write_json_atomic(workspace / 'book.json', book)
        msg = '全书所有 %d 个章节已完成，主 Agent 继续执行终局汇编: python scripts/merge_book.py --workspace "%s"' % (total, workspace)
        print(json.dumps({'ok': True, 'all_done': True, 'completed_chapter': k, 'message': msg}, ensure_ascii=False, indent=2))
        return 0

    next_k = k + 1
    next_dir = workspace / 'chapters' / ('ch%02d' % next_k)
    next_title = infos.get(next_k, {}).get('title', 'Chapter %d' % next_k)

    lines = []
    for s in cs:
        label = '- **第 %d 章（%s）**：' % (s['chapter'], s.get('title', ''))
        body = s.get('thesis', '')
        lines.append(label + (body if s['chapter'] >= k - 1 else body[:60] + ('…' if len(body) > 60 else '')))
    prev_summary = '\n'.join(lines) or '无'

    name_of = {t.get('uid'): t.get('zh') for t in ledger if t.get('uid')}
    terms_view = ledger if len(ledger) <= LEDGER_FULL_TABLE_MAX else [t for t in ledger if t.get('level') == '核心']
    rows = ['| 中文译名 | 原词 | 首次确立章节 | 锁定状态 | 概念依赖 | 核心界定 |', '| :--- | :--- | :--- | :--- | :--- | :--- |']
    for t in terms_view:
        deps = '、'.join(name_of.get(d, d) for d in t.get('depends_on', [])) or '无'
        rows.append('| %s | %s | 第 %s 章 | %s | %s | %s |' % (
            t.get('zh', ''), t.get('orig', ''), t.get('defined_in_chapter', '?'),
            '已锁定 (locked)' if t.get('locked', True) else '待定', deps, t.get('gloss') or '无'))
    table = '\n'.join(rows) if len(rows) > 2 else '暂无已固化术语。'
    if len(terms_view) < len(ledger):
        table += '\n\n（台账共 %d 条，此处仅列核心术语；写作任务单会按节自动注入全部相关已锁定译名。）' % len(ledger)

    template = (ROOT.parent / 'prompts' / 'P9-handover-template.md').read_text(encoding='utf-8')
    venv = ROOT.parent / '.venv' / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')
    values = {
        '{{SOURCE_LANG}}': book.get('source_lang', 'en'),
        '{{BOOK_TITLE}}': book.get('title', ''), '{{BOOK_AUTHOR}}': book.get('author', '未知作者'),
        '{{SKILL_DIR}}': str(ROOT.parent), '{{PYTHON}}': str(venv if venv.exists() else sys.executable),
        '{{WORKSPACE}}': str(workspace), '{{NEXT_CHAPTER_NUM}}': str(next_k), '{{NEXT_CHAPTER_TITLE}}': next_title,
        '{{CHAPTER_DIR}}': str(next_dir), '{{BOOK_THESIS}}': continuity.get('book_thesis') or book.get('title', ''),
        '{{TOTAL_CHAPTERS}}': str(total), '{{COMPLETED_CHAPTERS}}': str(k),
        '{{PREVIOUS_CHAPTERS_SUMMARY}}': prev_summary, '{{CURRENT_CHAPTER_NUM}}': str(k),
        '{{CURRENT_CHAPTER_THESIS}}': '（核心问题）%s；（结论，来源 %s）%s' % (question or '—', concl_source, conclusion),
        '{{CURRENT_CHAPTER_ENDING_TAIL}}': tail,
        '{{PENDING_QUESTIONS}}': '\n'.join('%d. %s' % (i + 1, q) for i, q in enumerate(pending)),
        '{{GLOBAL_TERM_TABLE}}': table,
    }
    prompt = template
    for key, val in values.items():
        prompt = prompt.replace(key, val)
    write_text_atomic(ch_dir / ('handover-to-ch%02d.prompt.md' % next_k), prompt)
    next_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(next_dir / 'handover-prompt.md', prompt)

    if k in infos:
        infos[k]['status'] = 'done'
    book['current_chapter'] = next_k
    write_json_atomic(workspace / 'book.json', book)

    print(json.dumps({'ok': True, 'completed_chapter': k, 'next_chapter': next_k,
                      'handover_prompt_path': str(ch_dir / ('handover-to-ch%02d.prompt.md' % next_k)),
                      'terms_count': len(ledger), 'forced': bool(args.force)}, ensure_ascii=False, indent=2))
    print('\n' + '=' * 80)
    print('第 %d 章已完成并同步账本。内部交接就绪，主 Agent 立即继续第 %d 章：' % (k, next_k))
    print('=' * 80 + '\n')
    print(prompt)
    return 0


if __name__ == '__main__':
    sys.exit(main())
