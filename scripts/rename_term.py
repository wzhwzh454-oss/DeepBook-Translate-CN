# -*- coding: utf-8 -*-
"""rename_term.py — 已锁定译名的受控改名（v2.0 没有任何解锁/迁移手段，早期误译会被永久固化）。

默认只做 dry-run 并报告各文件命中数；加 --apply 才会写入（每个被改文件先留 .bak）。
改动：台账条目的 zh（旧译名并入 alias_ban）、各章 term-plan.json 中同一原词的 zh、各章定稿/分节定稿文本。
之后必须对受影响章节重跑 --stage audit / --stage chapter（本脚本会删除其 chapter-checks.json 以强制重验）。"""
import argparse
import json
import re
import sys
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bt_common import norm_orig, read_json_strict, write_json_atomic, write_text_atomic  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def replaceable_matches(text, old, new, protected=()):
    if not old or old == new:
        return []
    protected_spans = [(m.start(), m.end()) for name in {new, *protected} if name and name != old and old in name for m in re.finditer(re.escape(name), text)]
    return [m for m in re.finditer(re.escape(old), text) if not any(a <= m.start() and m.end() <= b for a, b in protected_spans)]


def safe_replace_term(text, old, new, protected=()):
    pieces, cursor = [], 0
    for match in replaceable_matches(text, old, new, protected):
        pieces.extend((text[cursor:match.start()], new))
        cursor = match.end()
    return ''.join(pieces) + text[cursor:]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True, type=Path)
    ap.add_argument('--uid', required=True, help='台账 uid，如 c01:T1')
    ap.add_argument('--new-zh', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    ws = args.workspace.resolve()
    ledger = read_json_strict(ws / 'global-term-ledger.json', required=True)
    entry = next((t for t in ledger if t.get('uid') == args.uid), None)
    if entry is None:
        print(json.dumps({'ok': False, 'error': 'unknown uid %s' % args.uid}, ensure_ascii=False))
        return 1
    language = entry.get('source_lang', 'en')
    old, new, key = entry['zh'], args.new_zh.strip(), norm_orig(entry.get('orig'), language)
    if not new:
        print(json.dumps({'ok': False, 'error': 'new name is empty'}, ensure_ascii=False))
        return 1
    if old == new:
        print(json.dumps({'ok': False, 'error': 'new name equals old name'}, ensure_ascii=False))
        return 1
    if any(t.get('zh') == new and t is not entry for t in ledger):
        print(json.dumps({'ok': False, 'error': '%r already names another ledger term' % new}, ensure_ascii=False))
        return 1
    plans, texts = [], []
    for chapter in sorted((ws / 'chapters').glob('ch*')):
        plan = chapter / 'term-plan.json'
        if plan.exists():
            data = read_json_strict(plan)
            if any(norm_orig(t.get('orig'), t.get('source_lang', language)) == key and t.get('zh') == old for t in data.get('terms', [])):
                plans.append((plan, data))
        candidates = [
            chapter / 'chapter-final.md', chapter / 'merged-final.md', chapter / 'merged-draft-marked.md',
            chapter / 'p5-task.md', chapter / 'p5-review.md', chapter / 'chapter-summary.json',
            *sorted((chapter / 'sections').glob('*.md')),
            *sorted((chapter / 'sections').glob('*.json')),
        ]
        for text in candidates:
            if text.exists() and old in text.read_text(encoding='utf-8'):
                texts.append(text)
    protected = [t.get('zh') for t in ledger]
    counts = {str(t): len(replaceable_matches(t.read_text(encoding='utf-8'), old, new, protected)) for t in texts}
    report = {'ok': True, 'applied': args.apply, 'old': old, 'new': new,
              'plans': [str(p) for p, _ in plans],
              'texts': counts}
    report['note'] = '保护已存在的新译名及其他已登记复合术语；Agent 根据语境复核未登记复合词并重跑核验。'
    if args.apply:
        entry['zh'] = new
        entry['alias_ban'] = sorted(set(entry.get('alias_ban', [])) | {old})
        entry.setdefault('provenance', {})['renamed_from'] = old
        write_json_atomic(ws / 'global-term-ledger.json', ledger)
        for plan, data in plans:
            for t in data['terms']:
                if norm_orig(t.get('orig'), t.get('source_lang', language)) == key and t.get('zh') == old:
                    t['zh'] = new
            write_json_atomic(plan, data)
        refreshed_plans = [path for path, _ in plans]
        affected_chapters = {path.parent for path in refreshed_plans}
        affected_chapters.update(path.parent.parent if path.parent.name == 'sections' else path.parent for path in texts)
        refresh_after_ns = max((p.stat().st_mtime_ns for p in refreshed_plans), default=time.time_ns())
        for text in texts:
            write_text_atomic(text, safe_replace_term(text.read_text(encoding='utf-8'), old, new, [t.get('zh') for t in ledger]), backup=True)
            refresh_after_ns = max(refresh_after_ns, text.stat().st_mtime_ns)
        for chapter in sorted(affected_chapters):
            reports = chapter / 'reports'
            if reports.is_dir():
                for gate in [reports / 'chapter-checks.json', *reports.glob('audit-*-checks.json')]:
                    if gate.exists():
                        gate.unlink()
        ledger_path = ws / 'global-term-ledger.json'
        base_ns = max(time.time_ns(), ledger_path.stat().st_mtime_ns + 100_000_000)
        os.utime(ledger_path, ns=(base_ns, base_ns))
        stages = [
            refreshed_plans,
            sorted(p for p in texts if p.name.endswith(('-points.md', '-teaching-units.json'))),
            sorted(p for p in texts if p.name.endswith('-write-task.md')),
            sorted(p for p in texts if p.name.endswith('-revision.md')),
            sorted(p for p in texts if p.name.endswith('-final.md')),
            sorted(p for p in texts if p.name.startswith('coverage-')),
            sorted(p for p in texts if p not in refreshed_plans and p.name not in {
                'chapter-final.md', 'merged-final.md', 'merged-draft-marked.md', 'p5-task.md',
                'p5-review.md', 'chapter-summary.json'} and not p.name.endswith(('-points.md', '-teaching-units.json', '-write-task.md', '-revision.md', '-final.md')) and not p.name.startswith('coverage-')),
            sorted(p for p in texts if p.name in {'merged-draft-marked.md', 'p5-task.md', 'p5-review.md'}),
            sorted(p for p in texts if p.name in {'chapter-final.md', 'merged-final.md'}),
            sorted(p for p in texts if p.name == 'chapter-summary.json'),
        ]
        for index, stage in enumerate(stages, 1):
            stamp = base_ns + index * 100_000_000
            for path in stage:
                os.utime(path, ns=(stamp, stamp))
        report['next'] = '对受影响章节重跑 run_stage_checks --stage audit / --stage chapter，再重新运行 merge_book.py --check'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
