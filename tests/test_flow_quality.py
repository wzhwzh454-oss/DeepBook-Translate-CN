# -*- coding: utf-8 -*-
"""Focused regression tests for punctuation budgets and human P6 gates."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bt_common import sha256_text
from check_punctuation_budget import check_texts
from p6_review import review_state


def test_punctuation_budget_scope_and_locations():
    source = "# Source: title\nfront: ignore\n[P1] Source has: one; item — and one.\n[P2] Full-width：；——"
    translation = (
        "---\ntitle: metadata\n---\n# Chapter: heading\n"
        "Body:；—\n| cell: text |\n| --- | --- |\n"
        "`inline:;—` [link](https://x.test/a:b)\n"
        "```\ncode:;—\n```\n"
        "<!-- note:;—\nsecond line -->\n"
        "## 术语表\n术语：；——\n## 正文续\n"
    )
    result = check_texts(source, translation)
    assert result["source"]["counts"] == {"colon": 2, "semicolon": 2, "dash": 2}
    assert result["translation"]["counts"] == {"colon": 2, "semicolon": 1, "dash": 1}
    colon = result["translation"]["counts"]["colon"]
    assert colon == 2  # body and table-cell text only

    zero_budget = check_texts("[P1] No punctuation here", "# Heading\n\n正文：；——")
    assert [item["mark_type"] for item in zero_budget["over_limit"]] == ["colon", "semicolon", "dash"]
    location = zero_budget["over_limit"][0]["over_limit_locations"][0]
    assert location["line"] == 3 and location["column"] == 3

    no_anchor = check_texts("Unnumbered source:;—", "正文")
    assert no_anchor["ok"] is False and any("[P#]" in issue for issue in no_anchor["violations"])


def test_p6_report_state_and_hash_invalidation():
    with tempfile.TemporaryDirectory(prefix="bt-p6-") as temporary:
        workspace = Path(temporary)
        reports = workspace / "reports"
        reports.mkdir()
        final = workspace / "chapter-final.md"
        text = "本章正文。"
        final.write_text(text, encoding="utf-8")
        (reports / "p6-review.md").write_text("人工冷读完成。", encoding="utf-8")
        report = {
            "schema_version": 1,
            "review_type": "manual_cold_read",
            "review_completed": True,
            "reviewed_file": final.name,
            "report_file": "reports/p6-review.md",
            "reviewed_sha256": sha256_text(text),
            "high_risk_unresolved": [],
            "style_findings": [],
        }
        json_path = reports / "p6-review.json"
        json_path.write_text(json.dumps(report), encoding="utf-8")
        assert review_state(workspace, final)["status"] == "complete"

        report["style_findings"] = "malformed"
        json_path.write_text(json.dumps(report), encoding="utf-8")
        assert review_state(workspace, final)["status"] == "invalid"

        report["style_findings"] = []
        json_path.write_text(json.dumps(report), encoding="utf-8")
        final.write_text(text + "后改。", encoding="utf-8")
        assert review_state(workspace, final)["status"] == "stale"


def test_p6_task_uses_fence_longer_than_embedded_markdown():
    with tempfile.TemporaryDirectory(prefix="bt-p6-task-") as temporary:
        workspace = Path(temporary)
        (workspace / "chapter-final.md").write_text("正文\n```markdown\n嵌套围栏\n````\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "build_p6_task.py"), "--workspace", str(workspace)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        task = (workspace / "reports/p6-review-task.md").read_text(encoding="utf-8")
        assert "`````markdown" in task
        assert task.count("`````") == 2


def test_chapter_status_routes_missing_p6_to_review():
    with tempfile.TemporaryDirectory(prefix="bt-chapter-status-") as temporary:
        workspace = Path(temporary)
        chapter = workspace / "chapters/ch01"
        chapter.mkdir(parents=True)
        (chapter / "outline.json").write_text(json.dumps({"sections": []}), encoding="utf-8")
        (chapter / "term-plan.json").write_text(json.dumps({"terms": []}), encoding="utf-8")
        (chapter / "chapter-final.md").write_text("本章正文。", encoding="utf-8")
        (chapter / "source-numbered.md").write_text("[P1] Source body.", encoding="utf-8")
        (workspace / "runtime-strategy.json").write_text(json.dumps({
            "schema_version": 1,
            "workspace": str(workspace.resolve()),
            "host": {
                "capabilities": {"filesystem": {"read": True, "write": True}, "script_execution": True},
                "context_policy": {"kind": "unknown"},
            },
            "routing": {"mode": "B"},
        }), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "chapter_status.py"), "--workspace", str(chapter)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        state = json.loads(result.stdout)
        assert state["stage"] == "p6-review", state
        assert state["quality_gates"]["manual_p6"] == "missing"

        final_text = (chapter / "chapter-final.md").read_text(encoding="utf-8")
        reports = chapter / "reports"
        reports.mkdir()
        (reports / "p6-review.md").write_text("人工冷读完成。", encoding="utf-8")
        (reports / "p6-review.json").write_text(json.dumps({
            "schema_version": 1,
            "review_type": "manual_cold_read",
            "review_completed": True,
            "reviewed_file": "chapter-final.md",
            "report_file": "reports/p6-review.md",
            "reviewed_sha256": sha256_text(final_text),
            "high_risk_unresolved": [],
            "style_findings": [],
        }), encoding="utf-8")
        (chapter / "chapter-final.md").write_text(final_text + " P9 patch.", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "chapter_status.py"), "--workspace", str(chapter)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["stage"] == "p6-review", "P9 edits must invalidate the old P6 hash"


if __name__ == "__main__":
    failed = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print("PASS", name)
            except Exception as error:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "->", repr(error))
    sys.exit(1 if failed else 0)
