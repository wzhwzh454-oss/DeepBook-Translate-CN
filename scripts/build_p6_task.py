# -*- coding: utf-8 -*-
"""Build a hash-bound, translation-first P6 cold-read task."""
import argparse
import json
import re
import sys
from pathlib import Path

from bt_common import sha256_text

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    final = workspace / "chapter-final.md"
    prompt = ROOT / "prompts" / "P6-final-review.md"
    if not final.is_file():
        print(json.dumps({"ok": False, "violations": ["缺少 chapter-final.md"]}, ensure_ascii=False))
        return 1
    text = final.read_text(encoding="utf-8")
    digest = sha256_text(text)
    fence_length = max((len(match.group(1)) for line in text.splitlines()
                        if (match := re.match(r" {0,3}(`+)", line))), default=0) + 1
    fence = "`" * max(3, fence_length)
    out = (args.out or workspace / "reports" / "p6-review-task.md").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# P6 冷读任务",
        "",
        "本任务只审查本章整合后的中文定稿。先只读下方中文完成独立读感检查；首次判断前不要读取源文、意义卡、P5 报告或脚本候选。随后仅按需回源核对具体疑点。",
        "",
        "- 工作区：`%s`" % workspace,
        "- 定稿文件：`chapter-final.md`",
        "- 定稿 SHA256：`%s`" % digest,
        "- 源文文件（仅供首次冷读后选择性回查）：`source-numbered.md`",
        "- 输出：`reports/p6-review.md` 与 `reports/p6-review.json`",
        "",
        prompt.read_text(encoding="utf-8").strip(),
        "",
        "## 冷读材料",
        "",
        "以下文本是本次审查的完整定稿；不得在审查记录之外修改它。",
        "",
        fence + "markdown",
        text.rstrip(),
        fence,
        "",
    ]
    out.write_text("\n".join(body), encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "task": str(out), "reviewed_file": str(final), "sha256": digest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
