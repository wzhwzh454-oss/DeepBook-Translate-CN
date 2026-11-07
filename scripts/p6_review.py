# -*- coding: utf-8 -*-
"""Validate the human P6 attestation against the current integrated chapter."""
import json
from pathlib import Path

from bt_common import sha256_text


REVIEW_JSON = Path("reports/p6-review.json")
REVIEW_MARKDOWN = Path("reports/p6-review.md")
PENDING_ACTIONS = {"revise", "source_check"}


def review_state(workspace, final_path):
    workspace = Path(workspace).resolve()
    final_path = Path(final_path).resolve()
    json_path = workspace / REVIEW_JSON
    markdown_path = workspace / REVIEW_MARKDOWN
    state = {"ok": False, "status": "missing", "violations": [], "pending_actions": [], "style_findings": []}
    if not json_path.is_file() or not markdown_path.is_file():
        state["violations"].append("缺少 P6 人工冷读记录 reports/p6-review.md 和 reports/p6-review.json")
        return state
    try:
        report = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        state["status"] = "invalid"
        state["violations"].append("P6 JSON 记录不可读：%s" % error)
        return state
    if not isinstance(report, dict):
        state["status"] = "invalid"
        state["violations"].append("P6 JSON 记录必须是对象")
        return state
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        state["status"] = "invalid"
        state["violations"].append("P6 Markdown 记录不可读：%s" % error)
        return state
    if not markdown.strip():
        state["status"] = "invalid"
        state["violations"].append("P6 Markdown 冷读报告为空")
        return state

    structural_invalid = False
    expected = {
        "schema_version": 1,
        "review_type": "manual_cold_read",
        "review_completed": True,
        "reviewed_file": final_path.name,
    }
    for key, value in expected.items():
        if report.get(key) != value:
            structural_invalid = True
            state["violations"].append("P6 记录字段 %s 应为 %r" % (key, value))
    if report.get("report_file") != str(REVIEW_MARKDOWN).replace("\\", "/"):
        structural_invalid = True
        state["violations"].append("P6 report_file 必须指向 reports/p6-review.md")
    current_hash = sha256_text(final_path.read_text(encoding="utf-8")) if final_path.is_file() else None
    state["reviewed_sha256"] = report.get("reviewed_sha256")
    state["current_sha256"] = current_hash
    if report.get("reviewed_sha256") != current_hash:
        state["status"] = "stale"
        state["violations"].append("P6 记录未绑定当前整章定稿哈希；正文变化后必须复核")

    unresolved = report.get("high_risk_unresolved")
    if not isinstance(unresolved, list):
        structural_invalid = True
        state["violations"].append("P6 high_risk_unresolved 必须是数组")
        unresolved = ["invalid field"]
    for item in unresolved:
        state["violations"].append("P6 尚有未解决的高风险问题：%s" % str(item)[:160])

    findings = report.get("style_findings")
    if not isinstance(findings, list):
        structural_invalid = True
        state["violations"].append("P6 style_findings 必须是数组")
        findings = []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            structural_invalid = True
            state["violations"].append("P6 风格发现 #%d 格式无效" % index)
            continue
        for field in ("severity", "quote", "cause", "rule", "action", "reason"):
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                structural_invalid = True
                state["violations"].append("P6 风格发现 #%d 缺少 %s" % (index, field))
        if finding.get("action") not in ("revise", "retain"):
            structural_invalid = True
            state["violations"].append("P6 风格发现 #%d action 必须是 revise 或 retain" % index)
        if finding.get("action") in PENDING_ACTIONS:
            state["pending_actions"].append(finding)
    state["style_findings"] = findings
    if structural_invalid:
        state["status"] = "invalid"
    elif state["status"] not in ("stale", "invalid"):
        state["status"] = "pending-revisions" if state["pending_actions"] or unresolved else "complete"
    state["ok"] = not state["violations"] and state["status"] == "complete"
    if state["pending_actions"] and not state["violations"]:
        state["violations"].append("P6 留有需要修订或回源的风格候选；先处理后再审当前终稿")
    return state
