# -*- coding: utf-8 -*-
"""number_source.py — split source.md into blank-line paragraphs, prefix [Pk].

Usage:
  python3 number_source.py --source workspace/input/source.md \
      --out workspace/source-numbered.md

Output (stdout JSON): {"ok": bool, "paragraphs": int, "violations": [...]}
"""
import argparse
import io
import json
import re
import sys


def number_source(text):
    blocks = re.split(r'\n\s*\n', text)
    paras = [b.strip() for b in blocks if b.strip()]
    lines = ['[P%d] %s' % (i + 1, p) for i, p in enumerate(paras)]
    return paras, '\n\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    violations = []
    try:
        with io.open(args.source, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read source: %s' % e]},
                         ensure_ascii=False))
        return 1

    paras, numbered = number_source(text)
    if not paras:
        violations.append('source is empty')

    if not violations:
        with io.open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(numbered)

    ok = not violations
    print(json.dumps({'ok': ok, 'paragraphs': len(paras), 'violations': violations},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

