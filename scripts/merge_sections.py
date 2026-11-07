# -*- coding: utf-8 -*-
"""merge_sections.py — merge N section finals into one article.

Produces:
- merged-draft.md        clean text, one blank line between sections,
                         no headings or separators
- merged-draft-marked.md same, but each section prefixed with 【第k节】
                         on its own line (for P5 only)

Usage:
  python3 merge_sections.py --sections-dir workspace/sections --n 4 \
      --out workspace/merged-draft.md --out-marked workspace/merged-draft-marked.md

Output (stdout JSON): {"ok": bool, "violations": [...]}
"""
import argparse
import io
import json
import sys
import textutil


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sections-dir', required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--out-marked', required=True)
    args = ap.parse_args(argv)

    violations = []
    parts = []
    for k in range(1, args.n + 1):
        path = '%s/%d-final.md' % (args.sections_dir, k)
        try:
            with io.open(path, encoding='utf-8') as f:
                text = f.read().strip()
        except OSError:
            violations.append('missing section final: %s' % path)
            continue
        if not text:
            violations.append('section %d final is empty' % k)
            continue
        paras = textutil.split_paragraphs(text)
        parts.append('\n\n'.join(paras))

    if not violations:
        clean = '\n\n'.join(parts) + '\n'
        marked = '\n\n'.join('\u3010\u7b2c%d\u8282\u3011\n%s' % (k + 1, p)
                             for k, p in enumerate(parts)) + '\n'
        with io.open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(clean)
        with io.open(args.out_marked, 'w', encoding='utf-8', newline='\n') as f:
            f.write(marked)

    ok = not violations
    print(json.dumps({'ok': ok, 'violations': violations}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

