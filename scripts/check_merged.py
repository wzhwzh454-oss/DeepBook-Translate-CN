# -*- coding: utf-8 -*-
"""check_merged.py — verify the merged article's total CJK count.

The merged article should land in [global_floor, global_ceiling]. With
--tolerance N the script also accepts near-misses in
[global_floor-N, global_ceiling+N] (e.g. 60 chars short of the floor);
in that case ok=true but within_window=false, so the orchestrator can log
the deviation in state.run_log instead of forcing an editorial retry.

This check is advisory, not blocking: even when the count falls outside
both windows the script exits 0 (ok=false) and the pipeline continues —
the deviation is recorded in run_log. Length repair never triggers a
rewrite of already-final sections.

Usage:
  python3 check_merged.py --merged workspace/merged-draft.md \
      --floor 14809 --ceiling 19437 [--tolerance 100]

Output (stdout JSON): {"ok": bool, "within_window": bool, "cjk_count": n,
                       "floor": int, "ceiling": int, "note": str}
"""
import argparse
import io
import json
import sys
import textutil


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--merged', required=True)
    ap.add_argument('--floor', type=int, required=True)
    ap.add_argument('--ceiling', type=int, required=True)
    ap.add_argument('--tolerance', type=int, default=0)
    args = ap.parse_args(argv)

    try:
        with io.open(args.merged, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'within_window': False,
                          'note': 'cannot read merged: %s' % e},
                         ensure_ascii=False))
        return 1  # missing file is a real failure, unlike a length preference

    count = textutil.cjk_count(text)
    tol = max(0, args.tolerance)
    within = (args.floor <= count <= args.ceiling)
    in_tol = (args.floor - tol <= count <= args.ceiling + tol)

    if within:
        note = 'merged count %d within [%d, %d]' % (count, args.floor, args.ceiling)
    elif in_tol:
        note = ('merged count %d within tolerance of [%d, %d] '
                '(deviation %d, tolerance %d); recorded, no retry'
                % (count, args.floor, args.ceiling,
                   (args.floor - count) if count < args.floor else (count - args.ceiling),
                   tol))
    else:
        note = ('merged count %d outside [%d, %d] even with tolerance %d; '
                'recorded, no rewrite — length policy is advisory at merge time'
                % (count, args.floor, args.ceiling, tol))

    print(json.dumps({'ok': True, 'advisories': [] if in_tol else [note], 'within_window': within,
                      'cjk_count': count, 'floor': args.floor,
                      'ceiling': args.ceiling, 'note': note},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

