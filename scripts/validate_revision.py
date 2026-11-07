# -*- coding: utf-8 -*-
"""validate_revision.py — ensure a revision only deletes/merges draft text,
and split the P2G / P4 output into body + appendix.

P2G / P4 output format:
    一、修订后全文
    <body>
    二、附录（无内容的项写"无"）
    a. 结构性问题：...
    b. 存疑未删：...
    c. 源材料无依据：...  （仅两段式 P4 输出；P2G 融合模式无此项）

This script:
1. splits body from appendix (a literal leading "一、修订后全文" line and the
   appendix block are both mechanical scaffolding, not article text);
2. merged mode (P2G; --draft omitted): generation and deletive revision happen
   inside one call, so there is no separate reviser to guard against; only the
   body/appendix split and the empty-body check are kept, and the JSON output
   carries "mode": "merged";
3. two-stage mode (--draft given; the optional 回炉 fallback): validates body
   sentences against the draft: each passes if it is
   (a) verbatim equal to some draft sentence, or
   (b) a character subsequence of a single draft sentence (intra-sentence
       cuts), or
   (c) a character subsequence of two ADJACENT draft sentences concatenated
       (merge suture).
   Failing sentences may be at most 10% of all body sentences (tolerating
   R5 one-word swaps and sutures); above that the revision counts as a
   rewrite and must be bounced back;
4. parses appendix items a/b/c into structured lists ("无" entries dropped);
5. with --final-out, writes the body (verbatim, nothing else) to that path
   so S2d gets {k}-final.md mechanically.

All matching is whitespace-normalized.

Usage:
  # merged mode (P2G, default path)
  python3 validate_revision.py --revision workspace/sections/3-revision.md \
      [--final-out workspace/sections/3-final.md]
  # two-stage fallback (回炉): pass --draft to enable verbatim validation
  python3 validate_revision.py --draft workspace/sections/3-draft.md \
      --revision workspace/sections/3-revision.md \
      [--final-out workspace/sections/3-final.md]

Output (stdout JSON): {"ok": bool, "violations": [...], "fail_rate": f,
                       "failed_sentences": [...],
                       "appendix": {"a": [...], "b": [...], "c": [...]}}
                       (+ "mode": "merged" in merged mode)
"""
import argparse
import io
import json
import re
import sys
import textutil

MAX_FAIL_RATE = 0.10
BODY_HEAD_RE = re.compile(r'^\u4e00\u3001\u4fee\u8ba2\u540e\u5168\u6587\s*$')   # 一、修订后全文
APPENDIX_RE = re.compile(r'^\u4e8c\u3001\u9644\u5f55')                          # 二、附录
ITEM_RE = re.compile(r'^([abc])[\u3001\.]\s*(.*)$')                            # a、/ a.
# known label prefixes to strip from each appendix entry
LABEL_PREFIX = {
    'a': ('\u7ed3\u6784\u6027\u95ee\u9898\uff1a', '\u7ed3\u6784\u6027\u95ee\u9898:'),   # 结构性问题：
    'b': ('\u5b58\u7591\u672a\u5220\uff1a', '\u5b58\u7591\u672a\u5220:'),               # 存疑未删：
    'c': ('\u6e90\u6750\u6599\u65e0\u4f9d\u636e\uff1a', '\u6e90\u6750\u6599\u65e0\u4f9d\u636e:'),  # 源材料无依据：
}


def _strip_label(key, rest):
    for prefix in LABEL_PREFIX.get(key, ()):
        if rest.startswith(prefix):
            return rest[len(prefix):].strip()
    return rest


def split_body_appendix(revision):
    lines = revision.splitlines()
    appendix_at = None
    for i in range(len(lines) - 1, -1, -1):
        if APPENDIX_RE.match(lines[i].strip()):
            candidate = [line for line in lines[:i] if not BODY_HEAD_RE.match(line.strip())]
            if any(line.strip() for line in candidate):
                appendix_at = i
                break
    if appendix_at is None:
        body_lines = lines
        appendix_lines = []
    else:
        body_lines = lines[:appendix_at]
        appendix_lines = lines[appendix_at + 1:]
    # strip the scaffolding body heading if present
    body_lines = [l for l in body_lines if not BODY_HEAD_RE.match(l.strip())]
    body = '\n'.join(body_lines).strip('\n')

    appendix = {'a': [], 'b': [], 'c': []}
    for line in appendix_lines:
        s = line.strip()
        if not s or s == '\u65e0':
            continue
        m = ITEM_RE.match(s)
        if m:
            key, rest = m.group(1), m.group(2).strip()
            if not rest or rest == '\u65e0':
                continue
            rest = _strip_label(key, rest)
            # one entry = one verbatim item; never split on ； (c items are
            # verbatim sentences and ； is not a sentence boundary)
            if rest and rest != '\u65e0':
                appendix[key].append(rest)
    return body, appendix


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--draft', default=None,
                    help='draft file (two-stage mode); omit in merged mode '
                         '(P2G) to skip the draft comparison and only split '
                         'body/appendix')
    ap.add_argument('--revision', required=True)
    ap.add_argument('--final-out', '--out', dest='final_out', default=None,
                    help='write the body here (--out is the spelling used by SKILL.md/P9)')
    args = ap.parse_args(argv)

    try:
        draft = None
        if args.draft:
            with io.open(args.draft, encoding='utf-8') as f:
                draft = f.read()
        with io.open(args.revision, encoding='utf-8') as f:
            revision = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read input: %s' % e]},
                         ensure_ascii=False))
        return 1

    body, appendix = split_body_appendix(revision)

    if draft is None:
        # merged mode (P2G): generation and deletive revision happen inside
        # one call, so there is no separate reviser to guard against; keep
        # the body/appendix split and the empty-body check only.
        total = sum(1 for s in textutil.split_sentences(body)
                    if textutil.normalize_ws(s))
        violations = []
        if total == 0:
            violations.append('revision body has no sentences')
        ok = not violations
        if ok and args.final_out:
            with io.open(args.final_out, 'w', encoding='utf-8', newline='\n') as f:
                f.write(body + '\n')
        print(json.dumps({'ok': ok, 'violations': violations,
                          'fail_rate': 0.0, 'failed_sentences': [],
                          'appendix': appendix, 'mode': 'merged'},
                         ensure_ascii=False))
        return 0 if ok else 1

    d_raw = textutil.split_sentences(draft)
    d_norm = [textutil.normalize_ws(s) for s in d_raw]
    pairs = [d_norm[i] + d_norm[i + 1] for i in range(len(d_norm) - 1)]
    d_set = set(x for x in d_norm if x)

    failed = []
    total = 0
    for s in textutil.split_sentences(body):
        r = textutil.normalize_ws(s)
        if not r:
            continue
        total += 1
        if r in d_set:
            continue
        if any(textutil.is_subsequence(r, d) for d in d_norm if len(d) >= len(r)):
            continue
        if any(textutil.is_subsequence(r, p) for p in pairs if len(p) >= len(r)):
            continue
        failed.append(s.strip())

    fail_rate = (len(failed) / total) if total else 0.0
    violations = []
    if total == 0:
        violations.append('revision body has no sentences')
    elif fail_rate > MAX_FAIL_RATE:
        violations.append('fail rate %.2f%% > %.0f%% (%d/%d sentences not derived from draft)'
                          % (fail_rate * 100, MAX_FAIL_RATE * 100, len(failed), total))

    ok = not violations
    if ok and args.final_out:
        with io.open(args.final_out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body + '\n')

    print(json.dumps({'ok': ok, 'violations': violations,
                      'fail_rate': round(fail_rate, 4),
                      'failed_sentences': failed,
                      'appendix': appendix}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

