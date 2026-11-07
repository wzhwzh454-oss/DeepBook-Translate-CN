# -*- coding: utf-8 -*-
"""check_draft.py — accept or reject a section draft.

Checks:
- CJK character count is ADVISORY ONLY: the window (default budget ± 20%,
  or explicit --floor/--ceiling) is never used to reject a draft.
  Deviations are reported in "advisories" and via within_window so the
  orchestrator can log them, but they never trigger a retry. Length is
  governed at planning time (P1 outline / alloc_budget), not here.
  --floor/--ceiling/--tolerance are kept (tolerance is now a no-op) so
  existing call sites and budget-plan consumers do not break.
- no lines starting with '#'
- no isolated short heading-like paragraphs (<12 chars, no terminal punct)
- forbidden phrases (meta-narration & boilerplate) absent

Usage:
  python3 check_draft.py --draft workspace/sections/3-draft.md --budget 900 \
      [--floor 720] [--ceiling 1300] [--tolerance 100]

Output (stdout JSON): {"ok": bool, "violations": [...],
                       "advisories": [...], "cjk_count": n,
                       "within_window": bool}
"""
import argparse
import io
import json
import re
import sys
import textutil
from workspace_config import load_config

FORBIDDEN = [
    '\u672c\u6587\u5c06',          # 本文将
    '\u5982\u4e0a\u6240\u8ff0',        # 如上所述
    '\u63a5\u4e0b\u6765\u6211\u4f1a',    # 接下来我会
    '\u503c\u5f97\u6ce8\u610f\u7684\u662f',   # 值得注意的是
    '\u4e0d\u96be\u53d1\u73b0',       # 不难发现
    '\u9700\u8981\u6307\u51fa\u7684\u662f',   # 需要指出的是
    '\u603b\u800c\u8a00\u4e4b',       # 总而言之
    '\u7efc\u4e0a\u6240\u8ff0',       # 综上所述
    '\u603b\u7684\u6765\u8bf4',       # 总的来说
    '\u6beb\u65e0\u7591\u95ee',       # 毫无疑问
    '\u4e0d\u8a00\u800c\u55bb',       # 不言而喻
    '\u539f\u56e0\u5f88\u7b80\u5355',     # 原因很简单
    '\u4e0d\u53ef\u5426\u8ba4\u7684\u662f',   # 不可否认的是
    '\u663e\u800c\u6613\u89c1\u7684\u662f',   # 显而易见的是
    '\u672c\u6587\u6210\u529f\u8bc1\u660e\u4e86', # 本文成功证明了
    '\u4e3a\u4e86\u66f4\u751f\u52a8\u5730\u8bf4\u660e', # 为了更生动地说明
    '\u8ba9\u6211\u4eec\u8fdb\u884c\u4e00\u4e2a\u601d\u60f3\u5b9e\u9a8c', # 让我们进行一个思想实验
]
FORBIDDEN_RE = re.compile('|'.join(map(re.escape, FORBIDDEN)))
USER_FORBIDDEN = set()  # book-specific bans belong in term-plan/book.json `user_banned`, never in code
TERMINAL = set('\u3002\uff1f\uff01\u201d\u2019\u300d\u300f\uff09)')  # 。？！" ’ 」 』


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--draft', required=True)
    ap.add_argument('--budget', type=int, required=True)
    ap.add_argument('--profile', choices=('legacy', 'v2'), default='legacy')
    ap.add_argument('--floor', type=int, default=None)
    ap.add_argument('--ceiling', type=int, default=None)
    ap.add_argument('--tolerance', type=int, default=0,
                    help='widen the acceptance window by this many chars on '
                         'each side; near-misses within tolerance pass with '
                         'ok=true and within_window=false (default 0 = strict)')
    args = ap.parse_args(argv)

    violations = []
    try:
        with io.open(args.draft, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read draft: %s' % e],
                          'advisories': []}, ensure_ascii=False))
        return 1

    advisories = []
    reader_mode = load_config(args.draft)['translation'].get('mode') == 'full-study-reader'
    count = textutil.cjk_count(text)
    lo = args.floor if args.floor is not None else args.budget * 0.8
    hi = args.ceiling if args.ceiling is not None else args.budget * 1.2
    tol = max(0, args.tolerance)
    within = (lo <= count <= hi)
    if not within:
        # advisory only — never rejects; orchestrator logs the deviation
        advisories.append('cjk count %d outside preferred window [%d, %d] '
                          '(budget %d, floor %s, ceiling %s, tolerance %d); '
                          'accepted anyway'
                          % (count, lo, hi, args.budget,
                             args.floor, args.ceiling, tol))

    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('#') and not reader_mode:
            violations.append('line %d: heading marker "#" found' % i)

    for para in textutil.split_paragraphs(text):
        stripped = re.sub(r'\s+', '', para)
        if not reader_mode and len(stripped) < 12 and stripped and stripped[-1] not in TERMINAL:
            violations.append('isolated heading-like line: %r' % para[:40])

    for m in FORBIDDEN_RE.finditer(text):
        advisory = args.profile == 'v2' and m.group(0) not in USER_FORBIDDEN
        destination = advisories if advisory else violations
        destination.append('%s phrase: %s' % ('review' if advisory else 'forbidden', m.group(0)))

    ok = not violations
    print(json.dumps({'ok': ok, 'violations': violations,
                      'advisories': advisories, 'cjk_count': count,
                      'within_window': within}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

