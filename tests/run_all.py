# -*- coding: utf-8 -*-
"""run_all.py — 一次跑完 book-translator 的全部回归套件。

本机用法（Windows，技能根目录下任一处均可）：
    ".venv\\Scripts\\python.exe" tests\\run_all.py
    ".venv\\Scripts\\python.exe" tests\\run_all.py test_hardening        # 只跑部分

每个套件都是可独立执行的脚本（自带 __main__），这里用子进程跑，避免模块级状态与
sys.path 相互污染；编码固定 UTF-8，规避 cp936 控制台对 → ／ ✗ 等符号的报错。
"""
import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent


def suites(selected):
    names = sorted(p.stem for p in TESTS_DIR.glob('test_*.py'))
    if not selected:
        return names
    known = set(names)
    unknown = [s for s in selected if s not in known]
    if unknown:
        raise SystemExit('unknown suite(s): %s\navailable: %s' % (', '.join(unknown), ', '.join(names)))
    return selected


def main(argv):
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    results = []
    for name in suites(argv):
        path = TESTS_DIR / (name + '.py')
        print('=' * 72)
        print('RUN', path.relative_to(ROOT))
        completed = subprocess.run([sys.executable, str(path)], cwd=str(ROOT), env=env,
                                   capture_output=True, text=True, encoding='utf-8', errors='replace')
        tail = (completed.stdout or '').strip().splitlines()
        for line in tail[-12:]:
            print('   ', line)
        if completed.returncode != 0 and (completed.stderr or '').strip():
            print('---- stderr ----')
            print((completed.stderr or '').strip()[-2000:])
        results.append((name, completed.returncode))

    print('=' * 72)
    failed = [n for n, code in results if code != 0]
    for name, code in results:
        print('%s  %s' % ('PASS' if code == 0 else 'FAIL', name))
    print('%d/%d suites passed' % (len(results) - len(failed), len(results)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
