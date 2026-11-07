# -*- coding: utf-8 -*-
"""test_delivery_integrity.py — 全书交付质检（防空章、防跨章术语漂移、防残缺反查）专项测试 (v2.1).

v2.0 fixtures used a fake coverage file ("# Coverage PASS") that no real P8 audit ever produces, so the
'coverage defence' was only ever tested against its own magic marker. These fixtures carry a real
points / final / audit triple.
"""
import io
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
PYTHON = sys.executable
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

TEST_DIR = Path(tempfile.gettempdir()) / "bt-test-delivery-integrity"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

CH1_FINAL = """长期以来，认识论把知识界定为得到证实的真信念。

盖梯尔反例表明，持有得到证实的真信念，仍可能只是出于认识论运气（epistemic luck）。

因此，三要素不足以构成知识的充分条件。这一发现迫使认识论重新审视证成与真理之间的关系，并寻找新的条件。
"""
CH1_POINTS = """1.1｜定义｜作者｜知识长期被界定为得到证实的真信念。｜无｜[P1]｜是｜defined as justified true belief in tradition｜无｜断言｜无｜无
1.2｜主张｜作者｜盖梯尔反例表明持有得到证实的真信念仍可能只是出于认识论运气。｜可能｜[P2]｜是｜possess justified true belief by epistemic luck｜无｜断言｜无｜无
1.3｜结论｜作者｜因此三要素不足以构成知识的充分条件。｜无｜[P2]｜是｜three conditions are not sufficient for knowledge｜无｜断言｜无｜无"""
CH1_AUDIT = """1.1｜完整｜知识界定为得到证实的真信念｜保留
1.2｜完整｜仍可能只是出于认识论运气｜保留可能性限定
1.3｜完整｜三要素不足以构成知识的充分条件｜保留
"""
CH2_FINAL = """基础主义主张证成终止于基础信念，融贯论则主张证成来自信念之网的整体支持。

两种方案在架构证实信念时作出了不同的论证承诺，并各自面临无穷倒退与孤立自洽的质疑。

因此，证成理论的核心分歧在于证成关系是否必须有一个终点。
"""
CH2_POINTS = """1.1｜主张｜作者｜基础主义主张证成终止于基础信念。｜无｜[P3]｜是｜justification terminates in basic beliefs here｜无｜断言｜无｜无
1.2｜主张｜作者｜融贯论主张证成来自信念之网的整体支持。｜无｜[P4]｜是｜justification arises from a web of beliefs here｜无｜断言｜无｜无"""
CH2_AUDIT = """1.1｜完整｜基础主义主张证成终止于基础信念｜保留
1.2｜完整｜融贯论则主张证成来自信念之网的整体支持｜保留
"""


def setup_base_workspace():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)
    book = {"slug": "integrity-test", "title": "质检测试论集", "author": "测试作者", "total_chapters": 2, "current_chapter": 2,
            "chapters": [{"id": 1, "dir": "chapters/ch01", "title": "第一章：认识论基石"},
                         {"id": 2, "dir": "chapters/ch02", "title": "第二章：证实理论"}]}
    (TEST_DIR / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
    terms = [{"id": "T1", "zh": "认识论运气", "orig": "epistemic luck", "defined_in_chapter": 1, "locked": True,
              "depends_on": [], "gloss": "因偶然巧合而碰巧为真的认知状态", "alias_ban": ["认知运气", "认识偶然性", "运气"]}]
    (TEST_DIR / "global-term-ledger.json").write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
    for number, anchors, plan, final, points, audit in (
            (1, [[1, 2]], {"terms": terms}, CH1_FINAL, CH1_POINTS, CH1_AUDIT),
            (2, [[3, 4]], {"terms": []}, CH2_FINAL, CH2_POINTS, CH2_AUDIT)):
        ch = TEST_DIR / ("chapters/ch%02d" % number)
        (ch / "sections").mkdir(parents=True)
        (ch / "outline.json").write_text(json.dumps({"thesis": "q", "total_sections": 1, "sections": [{"k": 1, "anchors": anchors}]}, ensure_ascii=False), encoding="utf-8")
        (ch / "term-plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        (ch / "sections/1-points.md").write_text(points, encoding="utf-8")
        (ch / "sections/1-final.md").write_text(final, encoding="utf-8")
        (ch / "sections/coverage-1.md").write_text(audit, encoding="utf-8")
        (ch / "chapter-final.md").write_text(final, encoding="utf-8")
        source_paragraphs = [[1, 2], [3, 4]][number - 1]
        (ch / "source-numbered.md").write_text("\n\n".join(
            "[P%d] Source paragraph for delivery validation." % paragraph
            for paragraph in source_paragraphs
        ), encoding="utf-8")
        reports = ch / "reports"
        reports.mkdir()
        (reports / "p6-review.md").write_text("人工冷读完成；无未解决问题。", encoding="utf-8")
        (reports / "p6-review.json").write_text(json.dumps({
            "schema_version": 1,
            "review_type": "manual_cold_read",
            "review_completed": True,
            "reviewed_file": "chapter-final.md",
            "report_file": "reports/p6-review.md",
            "reviewed_sha256": hashlib.sha256(final.encode("utf-8")).hexdigest(),
            "high_risk_unresolved": [],
            "style_findings": [],
        }, ensure_ascii=False), encoding="utf-8")


def merge(*extra):
    for chapter in (TEST_DIR / "chapters").glob("ch*"):
        final = chapter / "chapter-final.md"
        report_path = chapter / "reports/p6-review.json"
        if final.is_file() and report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["reviewed_sha256"] = hashlib.sha256(final.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    res = subprocess.run([PYTHON, str(SCRIPTS_DIR / "merge_book.py"), "--workspace", str(TEST_DIR), *extra],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    try:
        return res, json.loads(res.stdout)
    except ValueError:
        return res, {}


def run():
    print("=== 开始全书交付质检 (Delivery Integrity) 专项防御测试 ===")

    print("\n--- 测试 1: 基准完备工程（含真实 points/final/audit）全绿 ---")
    setup_base_workspace()
    res, data = merge("--check")
    assert res.returncode == 0 and data["ok"] is True and data["violation_count"] == 0, res.stdout
    print("   -> 通过")

    print("\n--- 测试 2: 空章节与未定稿占位符 ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/chapter-final.md").write_text("（第 2 章暂未完成定稿）\n<!-- TODO: 待后续完善 -->\n", encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("暂未完成定稿" in v or "篇幅异常过短" in v for v in data["violations"]), data
    res, _ = merge("--strict")
    assert res.returncode != 0
    print("   -> 通过")

    print("\n--- 测试 3: 跨章术语漂移 ---")
    setup_base_workspace()
    drift = {"terms": [{"id": "T2d", "zh": "认知偶然性", "orig": "epistemic luck", "level": "核心", "gloss": "漂移译名", "alias_ban": []}]}
    (TEST_DIR / "chapters/ch02/term-plan.json").write_text(json.dumps(drift, ensure_ascii=False), encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("跨章术语漂移" in v and "epistemic luck" in v for v in data["violations"]), data
    print("   -> 通过")

    print("\n--- 测试 4: alias_ban 默认仅为提示；--strict-aliases 才拦截；user_banned 始终硬拦截 ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/chapter-final.md").write_text(CH2_FINAL + "\n我们必须注意认知运气的干扰。这个论证具有颠覆性。\n", encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 0 and any("认知运气" in a for a in data["advisories"]), ("alias_ban 应为 advisory", data)
    res, data = merge("--check", "--strict-aliases")
    assert res.returncode == 1 and any("认知运气" in v for v in data["violations"]), data
    plan = {"terms": [], "user_banned": ["颠覆性"]}  # 顶层 user_banned：v2.0 的交付检查完全忽略它
    (TEST_DIR / "chapters/ch02/term-plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("颠覆性" in v for v in data["violations"]), data
    print("   -> 通过")

    print("\n--- 测试 4b: 规范译名本身包含别名子串（'运气' ⊂ '认识论运气'）不得误报 ---")
    setup_base_workspace()
    res, data = merge("--check", "--strict-aliases")
    assert res.returncode == 0, data
    print("   -> 通过")

    print("\n--- 测试 5: 缺失/显式失败的反查报告 ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/sections/coverage-1.md").unlink()
    res, data = merge("--check")
    assert res.returncode == 1 and any("缺少覆盖核验反查报告" in v and "第 2 章" in v for v in data["violations"]), data
    (TEST_DIR / "chapters/ch02/sections/coverage-1.md").write_text("# Coverage Audit\n- [FAIL] 覆盖率仅80%未达标\n", encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("覆盖核验未通过" in v or "显式失败标记" in v for v in data["violations"]), data
    print("   -> 通过")

    print("\n--- 测试 6: 真实的失败行（缺失/改义）无需任何魔法标记也必须被拦截 ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/sections/coverage-1.md").write_text("1.1｜缺失｜｜没有对应\n1.2｜改义｜融贯论则主张证成来自信念之网的整体支持｜量词被改\n", encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("覆盖核验未通过" in v for v in data["violations"]), data
    print("   -> 通过")

    print("\n--- 测试 7: 缺少整章定稿时，分节稿不能冒充；汇编不得顺手写出 chapter-final.md ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/chapter-final.md").unlink()
    res, data = merge("--check")
    assert res.returncode == 1 and any("缺少定稿文本" in v for v in data["violations"]), data
    res, data = merge("--allow-violations")
    assert res.returncode == 0 and data["ok"] is False
    assert not (TEST_DIR / "chapters/ch02/chapter-final.md").exists(), "汇编产生了 chapter-final.md 副作用"
    print("   -> 通过")

    print("\n--- 测试 8: 默认汇编对违规失败关闭（fail-closed） ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/chapter-final.md").write_text("（第 2 章暂未完成定稿）\n", encoding="utf-8")
    res, _ = merge()
    assert res.returncode == 1 and not list((TEST_DIR / "output").glob("*.docx")), "默认模式不应在违规时产出交付物"
    print("   -> 通过")

    print("\n--- 测试 9: 两份分歧的整章定稿（chapter-final.md ≠ merged-final.md）视为歧义 ---")
    setup_base_workspace()
    (TEST_DIR / "chapters/ch02/merged-final.md").write_text(CH2_FINAL + "\nP5 修补后多出的一句。\n", encoding="utf-8")
    res, data = merge("--check")
    assert res.returncode == 1 and any("ambiguous final artifact" in v for v in data["violations"]), data
    print("   -> 通过")

    print("\n[OK] === 全书交付质检所有防御测试 100% 通过！ ===\n")
    return True


if __name__ == "__main__":
    run()
