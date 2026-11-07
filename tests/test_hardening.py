# -*- coding: utf-8 -*-
"""test_hardening.py — regression tests for every defect found in the v2.0 review (pytest-compatible,
no hard-coded paths, stdlib only). Each test names the v2.0 behaviour it pins down."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

import bt_common  # noqa: E402
import check_coverage  # noqa: E402
import check_readability  # noqa: E402
import intake_book  # noqa: E402
import operators  # noqa: E402
import quote_match  # noqa: E402
import orchestrate_book  # noqa: E402
import source_io  # noqa: E402
from check_force import check_force, pure_navigation  # noqa: E402


def sh(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=ENV)
    try:
        return r, json.loads(r.stdout.split("\n====", 1)[0] if "====" in r.stdout else r.stdout)
    except ValueError:
        return r, {}


def tmp():
    d = Path(tempfile.mkdtemp(prefix="bt-hard-"))
    return d


def mk_book(root, total=3):
    for i in range(1, total + 1):
        (root / "chapters" / ("ch%02d" % i) / "sections").mkdir(parents=True)
    (root / "book.json").write_text(json.dumps({"slug": "t", "title": "T", "author": "A", "total_chapters": total, "current_chapter": 1,
        "chapters": [{"id": i, "dir": "chapters/ch%02d" % i, "title": "C%d" % i, "status": "pending"} for i in range(1, total + 1)]}, ensure_ascii=False), encoding="utf-8")


def finish_chapter(root, k, plan_terms, text="正文内容，" * 40, gate=True):
    ch = root / "chapters" / ("ch%02d" % k)
    (ch / "outline.json").write_text(json.dumps({"thesis": "本章问题", "total_sections": 1, "sections": [{"k": 1, "conclusion": "计划结论", "open_question": "q", "anchors": [[1, 1]]}]}, ensure_ascii=False), encoding="utf-8")
    (ch / "term-plan.json").write_text(json.dumps({"version": 2, "terms": plan_terms}, ensure_ascii=False), encoding="utf-8")
    (ch / "chapter-final.md").write_text(text, encoding="utf-8")
    if gate:  # a valid gate report bound to the current text
        (ch / "reports").mkdir(exist_ok=True)
        (ch / "reports" / "chapter-checks.json").write_text(json.dumps({"ok": True, "meta": {"final_sha256": bt_common.sha256_text(text)}}), encoding="utf-8")


TERM = {"id": "T1", "zh": "认识论运气", "orig": "epistemic luck", "level": "核心", "gloss": "g", "role": "r", "example_src": None, "depends_on": [], "first_section": 1, "confusable_with": [], "alias_ban": []}


def runtime_strategy(mode, workspace):
    return {
        "schema_version": 1,
        "workspace": str(workspace.resolve()),
        "host": {"capabilities": {
            "filesystem": {"read": True, "write": True},
            "script_execution": True,
            "subagent": {"available": True, "fresh_context": True, "shared_workspace": True,
                         "permitted_for_task": True},
        }, "context_policy": {"kind": "unknown", "evidence": None}},
        "routing": {"mode": mode},
    }


# ------------------------------------------------------------------ handover
def test_handover_refuses_corrupt_ledger_instead_of_wiping_it():
    root = tmp(); mk_book(root)
    ledger = [{"uid": "c01:T%d" % i, "id": "T%d" % i, "zh": "术语%d" % i, "orig": "term %d" % i, "locked": True, "defined_in_chapter": 1, "depends_on": []} for i in range(1, 30)]
    text = json.dumps(ledger, ensure_ascii=False)
    (root / "global-term-ledger.json").write_text(text[: len(text) // 2], encoding="utf-8")  # truncated write
    finish_chapter(root, 1, [TERM])
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 1)
    assert r.returncode != 0 and d["ok"] is False and "corrupt" in d["error"]
    assert (root / "global-term-ledger.json").read_text(encoding="utf-8") == text[: len(text) // 2]  # untouched


def test_handover_rejects_drift_and_merges_nothing():
    root = tmp(); mk_book(root)
    (root / "global-term-ledger.json").write_text(json.dumps([{"uid": "c01:T1", "id": "T1", "zh": "认识论运气", "orig": "epistemic luck", "locked": True, "defined_in_chapter": 1, "depends_on": []}], ensure_ascii=False), encoding="utf-8")
    (root / "book.json").write_text(json.dumps({**json.loads((root / "book.json").read_text(encoding="utf-8")), "chapters": [{"id": i, "dir": "chapters/ch%02d" % i, "title": "C", "status": "done" if i == 1 else "pending"} for i in (1, 2, 3)]}), encoding="utf-8")
    finish_chapter(root, 2, [{**TERM, "zh": "认知偶然性", "orig": "Epistemic Lucks"}])  # re-translation, different inflection
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 2)
    assert r.returncode == 2 and d["conflicts"] and "drift" in d["conflicts"][0]
    ledger = json.loads((root / "global-term-ledger.json").read_text(encoding="utf-8"))
    assert len(ledger) == 1 and ledger[0]["zh"] == "认识论运气"
    assert json.loads((root / "book.json").read_text(encoding="utf-8"))["chapters"][1]["status"] == "pending"


def test_handover_requires_fresh_chapter_gate():
    root = tmp(); mk_book(root)
    finish_chapter(root, 1, [TERM], gate=False)
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 1)
    assert r.returncode != 0 and "门禁" in d["error"]
    finish_chapter(root, 1, [TERM])  # gate ok for this text...
    (root / "chapters/ch01/chapter-final.md").write_text("事后又改了正文。" * 30, encoding="utf-8")  # ...then edited
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 1)
    assert r.returncode != 0 and "过期" in d["error"]


def test_handover_namespaces_ids_and_prefers_unambiguous_final():
    root = tmp(); mk_book(root)
    finish_chapter(root, 1, [TERM, {**TERM, "id": "T2", "zh": "证成", "orig": "justification", "depends_on": ["T1"]}])
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 1)
    assert r.returncode == 0, r.stdout
    ledger = json.loads((root / "global-term-ledger.json").read_text(encoding="utf-8"))
    assert [t["uid"] for t in ledger] == ["c01:T1", "c01:T2"] and ledger[1]["depends_on"] == ["c01:T1"]
    (root / "chapters/ch02/merged-final.md").write_text("A", encoding="utf-8")
    finish_chapter(root, 2, [], text="B" * 100)
    (root / "chapters/ch02/merged-final.md").write_text("不同的内容" * 20, encoding="utf-8")
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 2)
    assert r.returncode != 0 and "ambiguous" in d["error"]


# ------------------------------------------------------------------ matching / audit
def test_quote_match_tolerates_typography_and_rejects_trivial_quotes():
    cases = [("Plato’s Theaetetus asks what knowledge is.", "Plato's Theaetetus asks what knowledge is"),
             ("Knowledge—if there is any—needs truth.", "Knowledge--if there is any--needs truth"),
             ("He calls it “epistemic luck” here.", 'He calls it "epistemic luck" here'),
             ("justi\u00adfication is required", "justification is required"),
             ("G\u00f6del proved incompleteness.", "Go\u0308del proved incompleteness.")]
    for source, quote in cases:
        assert quote_match.match_quote(quote, source), (source, quote)
    assert not bt_common.quote_long_enough("a") and bt_common.quote_long_enough("Only if a belief is true")


def test_coverage_rejects_one_character_evidence_and_flags_operator_inversion():
    pts = [{"id": "1.%d" % i, "bearing": "是", "kind": "主张", "statement": "作者认为知识必须得到证成", "qualifiers": "无"} for i in (1, 2, 3)]
    r = check_coverage.check_coverage("作者认为知识必须得到证成。", pts, "\n".join("1.%d｜完整｜知｜x" % i for i in (1, 2, 3)))
    assert r["ok"] is False
    inv = [{"id": "1.1", "bearing": "是", "kind": "主张", "statement": "并非所有信念都需要证成。", "qualifiers": "并非"}]
    r = check_coverage.check_coverage("所有信念都不需要证成。", inv, "1.1｜完整｜所有信念都不需要证成｜无", operator_mode="strict")
    assert r["ok"] is False and any("scope inversion" in v for v in r["violations"])
    assert operators.operator_parity("只有被证成才算知识。", "只有", "只要被证成就算知识。")
    assert operators.operator_parity("这个论证可能成立。", "可能", "这个论证必然成立。")
    assert not operators.operator_parity("作者认为知识需要证成。", "无", "作者认为知识需要证成。")
    disabled_advisories = check_coverage.check_coverage("所有信念都不需要证成。", inv, "1.1｜完整｜所有信念都不需要证成｜无", operator_mode="off")
    assert disabled_advisories["ok"] is False and any("scope inversion" in issue for issue in disabled_advisories["violations"])
    conditional = [{"id": "1.1", "bearing": "是", "kind": "限定", "statement": "仅当得到证成才是知识", "qualifiers": "仅当"}]
    result = check_coverage.check_coverage("只要得到证成就是知识。", conditional, "1.1｜完整｜只要得到证成就是知识｜无")
    assert result["ok"] is False and any("scope inversion" in issue for issue in result["violations"])
    modal = [{"id": "1.1", "bearing": "是", "kind": "主张", "statement": "这个论证可能成立", "qualifiers": "可能"}]
    result = check_coverage.check_coverage("这个论证必然成立。", modal, "1.1｜完整｜这个论证必然成立｜无")
    assert result["ok"] is False and any("modal inversion" in issue for issue in result["violations"])


def test_logical_negation_scope_and_lexical_boundaries():
    for point, evidence in (
        ("这一推论不成立。", "这一推论成立。"),
        ("实验结果未支持该假说。", "实验结果支持该假说。"),
        ("这一区分与道德评价无关。", "这一区分与道德评价有关。"),
    ):
        assert any(issue.startswith("negation:") for issue in operators.operator_parity(point, "无", evidence))
    assert any("absent from the point" in issue for issue in operators.operator_parity(
        "知觉经验具有概念内容。", "无", "知觉经验不具有概念内容。"))
    assert not operators.operator_parity("作者并不接受这一前提。", "并不", "作者不接受这一前提。")
    assert not operators.operator_parity("原文没有给出直接定义。", "没有", "原文未给出直接定义。")

    # Lexical lookalikes are ignored by negation matching, while quantifiers read the original text.
    for point, evidence in (
        ("作者接受这一前提并给出理由。", "作者不但接受这一前提，而且给出理由。"),
        ("安排持续变化。", "无论遇到什么情况，未来的安排都在不断变化。"),
        ("洪水漫过河谷后，救援人员先检查道路。", "洪水淹没河谷后，救援人员不妨先检查道路。"),
    ):
        assert not operators.operator_parity(point, "无", evidence)
    assert not operators.operator_parity(
        "每一位观察者都能到达现场。", "每一", "无一例外，每位观察者都能到达现场。")

    points = [{"id": "1.1", "bearing": "是", "kind": "主张",
               "statement": "并非所有信念都依赖推理。", "qualifiers": "并非、所有"}]
    article = "所有信念都不依赖推理。"
    audit = "1.1｜完整｜所有信念都不依赖推理｜无"
    assert any("scope inversion" in issue for issue in operators.operator_parity(
        points[0]["statement"], points[0]["qualifiers"], article))
    coverage = check_coverage.check_coverage(article, points, audit, operator_mode="off")
    assert coverage["ok"] is False and any("scope inversion" in issue for issue in coverage["violations"])

    assert any("modal inversion" in issue for issue in operators.operator_parity(
        "这一假说可能不成立。", "可能、不", "这一假说不可能成立。"))
    assert not operators.operator_parity(
        "这一方案不可能成功。", "不可能", "这一方案绝无可能成功。")
    assert not operators.operator_parity(
        "这一设想并非不可能实现。", "并非不可能", "这一设想可能实现。")
    assert any("double negation" in issue for issue in operators.operator_parity(
        "这一设想并非不可能实现。", "并非不可能", "这一设想不可能实现。"))
    assert not operators.operator_parity("我们不能不考虑这一反例。", "不能不", "我们必须考虑这一反例。")
    assert not operators.operator_parity("这一条件无不受到影响。", "无不", "这一条件都受到影响。")
    assert not operators.operator_parity("参与者未尝不感到意外。", "未尝不", "参与者感到意外。")
    assert not operators.operator_parity("机构没有无不良记录。", "无", "机构没有不良记录。")

    modal_points = [{"id": "1.1", "bearing": "是", "kind": "主张",
                     "statement": "这一假说不可能成立。", "qualifiers": "不可能"}]
    modal_article = "这一假说可能不成立。"
    modal_audit = "1.1｜完整｜这一假说可能不成立｜无"
    modal_coverage = check_coverage.check_coverage(
        modal_article, modal_points, modal_audit, operator_mode="off")
    assert modal_coverage["ok"] is False and any(
        "modal inversion" in issue for issue in modal_coverage["violations"])

    assert not operators.operator_parity("仅靠直觉不易维持这一区分。", "不易", "仅靠直觉难以维持这一区分。")
    assert any("difficulty:" in issue for issue in operators.operator_parity(
        "仅靠直觉难以维持这一区分。", "难以", "仅靠直觉即可维持这一区分。"))
    shifted = operators.operator_parity("这一条件不是必要条件。", "不是", "这一条件难以成为必要条件。")
    assert any("negation/difficulty shift" in issue for issue in shifted)


def test_force_check_is_negation_aware_and_navigation_exemption_is_tight():
    pts = [{"id": "1.1", "force": "试探", "bearing": "是", "source_quote": "may be"}]
    cov = {"entries": [{"id": "1.1", "status": "完整", "evidence": "作者认为这或许成立", "explanation": "无力度升级，也无力度降级"}], "reverse_entries": []}
    assert check_force("作者认为这或许成立。", pts, cov)["ok"] is True
    assert pure_navigation("接下来我们介绍作者如何解决这个问题。")
    assert not pure_navigation("下面我们将说明知识是被证成的真信念。")
    assert not pure_navigation("接下来我们讨论归纳不可靠的原因。")


# ------------------------------------------------------------------ outline / patches / sheets
OUTLINE = """# 大纲头部
- 全文核心问题：知识是什么？
- 总节数：1；总字数预算：1000
- 未纳入内容：无

### 第 1 节：提出问题
- 位置：首节
- 本节子问题：什么是知识？
- 承接的遗留问题：无
- 核心内容：传统定义。
- 本节结论：传统定义有困难。
- 承担链段：含最强异议
- 源文锚点：P1–P3
- 禁写清单：无
- 遗留问题：留给下一章
- 字数预算：1000
- 阶段号：1
- 阶段全称：提出问题
- 阶段简称：问题

# 术语表初稿
知识｜knowledge｜1

# 自查表
a. 论证各项有主节、无重复展开：通过＋依据
b. 问题链闭合：通过＋依据
c. 参考预算与内容量相称：通过＋依据
d. 源文锚点非空且未把承重项列为未纳入：通过＋依据
"""


def test_outline_must_account_for_every_source_paragraph():
    d = tmp()
    (d / "source-numbered.md").write_text("\n\n".join("[P%d] Paragraph %d with real argument content in it." % (i, i) for i in range(1, 9)), encoding="utf-8")
    (d / "outline.md").write_text(OUTLINE, encoding="utf-8")
    r, data = sh("check_outline.py", "--outline", d / "outline.md", "--numbered", d / "source-numbered.md", "--out-json", d / "o.json")
    assert data["ok"] is False and any("P4" in v for v in data["violations"]), data
    (d / "outline.md").write_text(OUTLINE.replace("未纳入内容：无", "未纳入内容：P4–P8 本章之外的附论").replace("P1–P3", "P1–P3"), encoding="utf-8")
    r, data = sh("check_outline.py", "--outline", d / "outline.md", "--numbered", d / "source-numbered.md", "--out-json", d / "o.json")
    assert data["ok"] is True, data


def test_apply_patches_is_all_or_nothing_and_never_merges_paragraphs():
    d = tmp()
    (d / "m.md").write_text("【第1节】\n第一段结尾句。\n\n第二段开头句。继续。\n", encoding="utf-8")
    (d / "p.md").write_text("1｜T1｜替换｜第一段结尾句。第二段开头句｜合并句\n1｜T1｜替换｜继续｜延续\n", encoding="utf-8")
    r, data = sh("apply_patches.py", "--patches", d / "p.md", "--marked", d / "m.md", "--out", d / "o.md", "--profile", "v2")
    assert data["ok"] is False and data["written"] is False and not (d / "o.md").exists()
    assert any("paragraph boundary" in (p.get("reason") or "") for p in data["patch_log"])


def test_validate_revision_accepts_documented_out_flag():
    d = tmp()
    (d / "r.md").write_text("一、修订后全文\n\n作者主张知识需要证成。\n\n二、附录\na. 结构性问题：无\n", encoding="utf-8")
    r, _ = sh("validate_revision.py", "--revision", d / "r.md", "--out", d / "final.md")
    assert r.returncode == 0 and (d / "final.md").exists()


def _write_sheet_fixture(d, statement, hint="无"):
    (d / "sections").mkdir(exist_ok=True)
    (d / "outline.json").write_text(json.dumps({"thesis": "q", "total_sections": 1, "sections": [{"k": 1, "sub_question": "什么是知识？", "core_content": "传统定义", "conclusion": "有困难", "chain_role": "破题", "anchors": [[1, 1]], "prohibited": [], "inherits": "无", "open_question": "无", "budget": 300}]}, ensure_ascii=False), encoding="utf-8")
    (d / "sections/1-points.md").write_text("1.1｜定义｜作者｜%s｜无｜[P1]｜是｜Knowledge has traditionally been defined as justified true belief.｜%s｜断言｜无｜无" % (statement, hint), encoding="utf-8")


def test_write_sheet_blocks_english_leakage_and_auto_loads_ledger():
    d = tmp()
    (d / "chapters" / "ch02").mkdir(parents=True)
    (d / "global-term-ledger.json").write_text(json.dumps([{"uid": "c01:T1", "zh": "认识论运气", "orig": "epistemic luck", "locked": True, "gloss": "靠运气为真"}], ensure_ascii=False), encoding="utf-8")
    ch = d / "chapters" / "ch02"
    _write_sheet_fixture(ch, "Gettier showed that the tripartite account fails because of epistemic luck here.")
    tpl = ROOT / "prompts" / "P3-write-sheet.md"
    args = ["--mode", "write", "--k", 1, "--outline-json", ch / "outline.json", "--points", ch / "sections/1-points.md", "--sections-dir", ch / "sections", "--template", tpl, "--out", ch / "sections/1-write-task.md"]
    r, data = sh("build_task_sheet.py", *args)
    assert data["ok"] is False and any("English leakage" in v for v in data["violations"]) and not (ch / "sections/1-write-task.md").exists()
    _write_sheet_fixture(ch, "知识传统上被定义为得到证成的真信念。")
    r, data = sh("build_task_sheet.py", *args)
    sheet = (ch / "sections/1-write-task.md").read_text(encoding="utf-8")
    assert data["ok"] is True and "认识论运气" in sheet, "ledger must be auto-loaded even when the scope text does not mention the term"
    assert "Knowledge has traditionally" not in sheet


# ------------------------------------------------------------------ intake
def test_dehyphenation_keeps_real_compounds():
    out = intake_book.clean_book_text("A self-\nevident truth, a non-\nideal theory, post-\nGettier work, and justi-\nfication; justification again.")
    assert "self-evident" in out and "non-ideal" in out and "post-Gettier" in out and "justification" in out and "justi-" not in out


def test_chapter_detection_ignores_subsections_toc_and_back_matter():
    w = "word " * 120
    text = "Contents\n\nChapter 1  Knowledge ..... 3\nChapter 2  Justification .... 40\n\n## Chapter 1 Knowledge\n\n%s\n\n## 1.1 What is knowledge\n\n%s\n\n## Mill on Liberty\n\n%s\n\n## Chapter 2 Justification\n\n%s\n\n## 2.1 Foundationalism\n\n%s\n\n## Bibliography\n\nSmith (2001).\n" % (w, w, w, w, w)
    chapters, back = intake_book.split_into_chapters(intake_book.clean_book_text(text), return_back_matter=True)
    assert [c["title"] for c in chapters] == ["Chapter 1 Knowledge", "Chapter 2 Justification"] and "Smith" in back


# ------------------------------------------------------------------ graph
def test_term_graph_layers_cycles_and_forward_refs():
    ledger = [{"uid": "c01:T1", "id": "T1", "zh": "知识", "orig": "knowledge", "defined_in_chapter": 1, "depends_on": []},
              {"uid": "c01:T2", "id": "T2", "zh": "证成", "orig": "justification", "defined_in_chapter": 1, "depends_on": ["T1"]},
              {"uid": "c02:T1", "id": "T1", "zh": "葛梯尔案例", "orig": "Gettier case", "defined_in_chapter": 2, "depends_on": ["c01:T2", "ledger:知识"]},
              {"uid": "c02:T2", "id": "T2", "zh": "运气", "orig": "luck", "defined_in_chapter": 2, "depends_on": ["T3"]},
              {"uid": "c02:T3", "id": "T3", "zh": "偶然", "orig": "accident", "defined_in_chapter": 2, "depends_on": ["T2"]},
              {"uid": "c01:T9", "id": "T9", "zh": "早期概念", "orig": "early", "defined_in_chapter": 1, "depends_on": ["c02:T1"]}]
    g = bt_common.analyze_term_graph(ledger)
    assert g["layers"][0] == ["c01:T1"] and "c01:T2" in g["layers"][1]
    assert any(set(c) == {"c02:T2", "c02:T3"} for c in g["cycles"])
    assert g["forward_refs"] == [{"term": "c01:T9", "depends_on": "c02:T1"}]
    assert "graph TD" in bt_common.term_graph_mermaid(g)


def test_handover_prompt_is_fully_rendered_and_carries_isolation_protocol():
    root = tmp(); mk_book(root)
    finish_chapter(root, 1, [TERM])
    r, d = sh("generate_handover.py", "--workspace", root, "--chapter", 1)
    assert r.returncode == 0, r.stdout
    prompt = (root / "chapters/ch01/handover-to-ch02.prompt.md").read_text(encoding="utf-8")
    assert "{{" not in prompt and "runtime-strategy.json" in prompt and "chapter_status.py" in prompt and "--leak-source" in prompt


def test_chapter_status_reports_next_action_through_the_stages():
    root = tmp(); mk_book(root, 1)
    ch = root / "chapters/ch01"
    (root / "runtime-strategy.json").write_text(json.dumps(runtime_strategy("B", root)), encoding="utf-8")
    r, d = sh("chapter_status.py", "--workspace", ch)
    assert d["stage"] == "outline"
    (ch / "outline.json").write_text(json.dumps({"sections": [{"k": 1}]}), encoding="utf-8")
    assert sh("chapter_status.py", "--workspace", ch)[1]["stage"] == "term-plan"
    (ch / "term-plan.json").write_text("{}", encoding="utf-8")
    assert sh("chapter_status.py", "--workspace", ch)[1]["stage"] == "section-1:extract"
    base = 1_700_000_000
    for i, name in enumerate(["1-points.md", "1-teaching-units.json", "1-write-task.md", "1-revision.md", "1-final.md", "coverage-1.md"]):
        path = ch / "sections" / name
        path.write_text("x", encoding="utf-8")
        os.utime(path, (base + i, base + i))
    assert sh("chapter_status.py", "--workspace", ch)[1]["stage"] == "merge"
    os.utime(ch / "sections/1-points.md", (base + 99, base + 99))  # points edited after the task sheet was built
    assert sh("chapter_status.py", "--workspace", ch)[1]["stage"] == "section-1:write-task"


def test_runtime_strategy_probes_routes_and_stays_out_of_content_gates():
    root = tmp(); mk_book(root, 1)
    r, data = sh("orchestrate_book.py", "--workspace", root, "--describe")
    assert r.returncode == 0 and data["stage"] == "host-probe"
    assert str(root / "runtime-strategy.json") in data["expected_outputs"]
    assert "OCR" in data["instructions"] and "用户未同意前" in data["instructions"]
    assert "handoff_trigger" in data["instructions"] and "能否开启新对话" in data["instructions"]

    strategy = runtime_strategy("A", root)
    (root / "runtime-strategy.json").write_text(json.dumps(strategy), encoding="utf-8")
    assert orchestrate_book.runtime_strategy(root)["routing"]["mode"] == "A"
    assert orchestrate_book.writer_route(strategy)["prefer_fresh_context"] is True
    assert orchestrate_book.writer_route(strategy)["dispatch"] == "fresh_context_subagent"
    assert orchestrate_book.writer_route(runtime_strategy("B", root))["prefer_fresh_context"] is False
    manual = orchestrate_book.writer_route(runtime_strategy("C", root))
    assert manual["dispatch"] == "manual_handover" and manual["prefer_fresh_context"] is False
    reviewer = orchestrate_book.annotate_runtime_action(
        {"kind": "agent", "role": "source-reviewer", "instructions": "review"}, root, strategy)
    assert reviewer["routing_mode"] == "A" and reviewer["host_dispatch"] == "fresh_context_subagent"
    assert reviewer["prefer_fresh_context"] is True and "expected_outputs" in reviewer["instructions"]
    assert all("runtime-strategy.json" not in str(path) for path in
               orchestrate_book.tracked_inputs(root, json.loads((root / "book.json").read_text(encoding="utf-8"))))

    strategy["host"]["capabilities"]["subagent"]["permitted_for_task"] = False
    (root / "runtime-strategy.json").write_text(json.dumps(strategy), encoding="utf-8")
    try:
        orchestrate_book.runtime_strategy(root)
    except bt_common.StateError:
        pass
    else:
        raise AssertionError("inconsistent A strategy must fail closed")


def test_chapter_status_write_hint_follows_runtime_route():
    root = tmp(); mk_book(root, 1)
    ch = root / "chapters/ch01"
    r, data = sh("chapter_status.py", "--workspace", ch)
    assert r.returncode == 0 and data["stage"] == "host-probe"

    (ch / "outline.json").write_text(json.dumps({"sections": [{"k": 1}]}), encoding="utf-8")
    (ch / "term-plan.json").write_text("{}", encoding="utf-8")
    sec = ch / "sections"
    for name in ("1-points.md", "1-teaching-units.json", "1-write-task.md"):
        (sec / name).write_text("x", encoding="utf-8")

    for mode, expected in (("A", "模式 A"), ("B", "模式 B"), ("C", "模式 C")):
        (root / "runtime-strategy.json").write_text(json.dumps(runtime_strategy(mode, root)), encoding="utf-8")
        r, data = sh("chapter_status.py", "--workspace", ch)
        assert r.returncode == 0 and data["stage"] == "section-1:write", r.stdout
        assert expected in data["next"]
        assert data["runtime_mode"] == mode


def test_rename_term_is_dry_run_by_default_and_migrates_on_apply():
    root = tmp(); mk_book(root, 2)
    (root / "global-term-ledger.json").write_text(json.dumps([{"uid": "c01:T1", "id": "T1", "zh": "认知运气", "orig": "epistemic luck", "locked": True, "defined_in_chapter": 1, "depends_on": [], "alias_ban": []}], ensure_ascii=False), encoding="utf-8")
    finish_chapter(root, 1, [{**TERM, "zh": "认知运气"}], text="这里讨论认知运气。" * 20, gate=True)
    r, d = sh("rename_term.py", "--workspace", root, "--uid", "c01:T1", "--new-zh", "认识论运气")
    assert d["applied"] is False and "认知运气" in (root / "chapters/ch01/chapter-final.md").read_text(encoding="utf-8")
    r, d = sh("rename_term.py", "--workspace", root, "--uid", "c01:T1", "--new-zh", "认识论运气", "--apply")
    assert d["applied"] is True
    assert "认识论运气" in (root / "chapters/ch01/chapter-final.md").read_text(encoding="utf-8")
    led = json.loads((root / "global-term-ledger.json").read_text(encoding="utf-8"))
    assert led[0]["zh"] == "认识论运气" and "认知运气" in led[0]["alias_ban"]
    assert not (root / "chapters/ch01/reports/chapter-checks.json").exists(), "gate must be invalidated so the chapter is re-verified"


def test_outline_failure_removes_stale_json_and_japanese_body_is_not_heading_like():
    d = tmp()
    (d / "book.json").write_text(json.dumps({"source_lang": "ja"}), encoding="utf-8")
    (d / "outline.json").write_text("stale", encoding="utf-8")
    source = "\n\n".join("[P%d] この段落には重要な哲学的議論と具体的な根拠が含まれています。" % i for i in range(1, 7))
    (d / "source-numbered.md").write_text(source, encoding="utf-8")
    (d / "outline.md").write_text(OUTLINE, encoding="utf-8")
    r, data = sh("check_outline.py", "--outline", d / "outline.md", "--numbered", d / "source-numbered.md", "--out-json", d / "outline.json")
    assert r.returncode != 0 and data["ok"] is False
    assert any("P4" in issue for issue in data["violations"])
    assert not (d / "outline.json").exists()


def test_readability_candidates_cover_common_ai_tells_and_respect_source_metaphor():
    bad = ("值得注意的是，自我认知绝非锁在玻璃柜里的僵死标本，也不是一盘散沙——原因如下："
           "一方面，我们不够聪明；另一方面，环境在变。\n\n"
           "这个场景只给出结果。这个场景没有提供理由。这个场景缺乏根据。这个场景不能成立。"
           "因此，我们不难发现这一规则被彻底焊死了。然而，这并不意味着所有系统都不可信，也不是说我们要检查全部代码。")
    result = check_readability.check_readability(bad, candidates=True)
    assert result["ok"] is True, "style candidates remain advisory"
    reasons = {reason for item in result["candidates"] for reason in item["reasons"]}
    assert {"punctuation_crutch_dash", "punctuation_crutch_colon", "punctuation_crutch_semicolon",
            "choppy_chain", "anaphora_repeat", "disclaimer_tail"} <= reasons
    assert any(reason.startswith("dead_metaphor:") for reason in reasons)
    assert "register_pollution" in reasons
    exempt = check_readability.check_readability(
        "作者在这里提到了玻璃柜里的僵死标本。", candidates=True,
        source_points_text="1.1｜意象｜作者｜玻璃柜里的僵死标本｜")
    exempt_reasons = {reason for item in exempt["candidates"] for reason in item["reasons"]}
    assert not any(reason.startswith("dead_metaphor:") for reason in exempt_reasons)


def test_v2_style_patches_preserve_terms_and_logical_operators():
    d = tmp()
    (d / "terms.json").write_text(json.dumps([{"zh": "可解释性", "orig": "explainability"}], ensure_ascii=False), encoding="utf-8")
    (d / "marked.md").write_text(
        "【第1节】\n这个场景只给出可解释性结果。这个场景没有提供理由。因此，这个场景并非所有时候都满足条件。\n\n"
        "说白了，这一规则绝非玻璃柜里的僵死标本，不能把条件焊死。\n", encoding="utf-8")
    (d / "patches.md").write_text(
        "1｜T13｜替换｜这个场景只给出可解释性结果。这个场景没有提供理由。因此，这个场景并非所有时候都满足条件。｜这一情形只给出了可解释性结果而未交代理由，并非所有时候都满足条件。\n"
        "1｜T14｜替换｜说白了，这一规则绝非玻璃柜里的僵死标本，不能把条件焊死。｜这一规则并非一开始就固定不变，我们很难把它的适用条件完全锁死。\n", encoding="utf-8")
    r, data = sh("apply_patches.py", "--patches", d / "patches.md", "--marked", d / "marked.md", "--out", d / "out.md", "--terms-json", d / "terms.json", "--profile", "v2")
    assert r.returncode == 0 and data["ok"] is True, data
    out = (d / "out.md").read_text(encoding="utf-8")
    assert "可解释性" in out and "说白了" not in out and "焊死" not in out
    (d / "bad-patches.md").write_text(
        "1｜T13｜替换｜这个场景只给出可解释性结果。这个场景没有提供理由。因此，这个场景并非所有时候都满足条件。｜这一情形只给出了结果而未交代理由，所有时候都不满足条件。\n", encoding="utf-8")
    r, data = sh("apply_patches.py", "--patches", d / "bad-patches.md", "--marked", d / "marked.md", "--out", d / "bad.md", "--terms-json", d / "terms.json", "--profile", "v2")
    assert r.returncode != 0 and data["ok"] is False and not (d / "bad.md").exists()


def test_rename_term_refreshes_intermediates_and_only_removes_gate_reports():
    root = tmp(); mk_book(root, 1)
    (root / "global-term-ledger.json").write_text(json.dumps([{"uid": "c01:T1", "id": "T1", "zh": "认知运气", "orig": "epistemic luck", "locked": True, "defined_in_chapter": 1, "depends_on": [], "alias_ban": []}], ensure_ascii=False), encoding="utf-8")
    finish_chapter(root, 1, [{**TERM, "zh": "认知运气"}], text="这里讨论认知运气。" * 20, gate=True)
    ch = root / "chapters/ch01"
    section_files = ["1-points.md", "1-teaching-units.json", "1-write-task.md", "1-revision.md", "1-final.md", "coverage-1.md"]
    for name in section_files:
        (ch / "sections" / name).write_text("认知运气", encoding="utf-8")
    reports = ch / "reports"
    (reports / "audit-1-checks.json").write_text("{}", encoding="utf-8")
    (reports / "draft-1-checks.json").write_text("{}", encoding="utf-8")
    r, data = sh("rename_term.py", "--workspace", root, "--uid", "c01:T1", "--new-zh", "认识论运气", "--apply")
    assert r.returncode == 0 and data["applied"] is True
    plan_mtime = (ch / "term-plan.json").stat().st_mtime_ns
    assert all(path.stat().st_mtime_ns >= plan_mtime for path in [ch / "chapter-final.md", *(ch / "sections" / name for name in section_files)])
    assert (root / "global-term-ledger.json").stat().st_mtime_ns < plan_mtime
    assert (ch / "sections/1-points.md").stat().st_mtime_ns < (ch / "sections/1-write-task.md").stat().st_mtime_ns < (ch / "sections/1-revision.md").stat().st_mtime_ns < (ch / "sections/1-final.md").stat().st_mtime_ns < (ch / "sections/coverage-1.md").stat().st_mtime_ns
    assert not (reports / "audit-1-checks.json").exists() and not (reports / "chapter-checks.json").exists()
    assert (reports / "draft-1-checks.json").exists()


def test_book_outline_reopens_when_continuity_thesis_is_still_placeholder():
    root = tmp(); mk_book(root, 1)
    (root / "book-outline.md").write_text("initial", encoding="utf-8")
    (root / "book-continuity.json").write_text(json.dumps({"book_thesis": "（待在第1章或全书规划中具体提炼）", "book_arc": ""}, ensure_ascii=False), encoding="utf-8")
    book = json.loads((root / "book.json").read_text(encoding="utf-8"))
    action = orchestrate_book.next_action(root, book, runtime_strategy("B", root))
    assert action["stage"] == "book-outline" and str(root / "book.json") in action["expected_outputs"]


def test_write_sheet_carries_genre_style_profile():
    d = tmp()
    (d / "chapters/ch01/sections").mkdir(parents=True)
    (d / "book.json").write_text(json.dumps({"source_lang": "fr", "style_profile": {"genre_family": "continental_critique"}}, ensure_ascii=False), encoding="utf-8")
    ch = d / "chapters/ch01"
    _write_sheet_fixture(ch, "作者沿着概念关系展开分析。")
    out = ch / "sections/1-write-task.md"
    args = ["--mode", "write", "--k", 1, "--outline-json", ch / "outline.json", "--points", ch / "sections/1-points.md", "--sections-dir", ch / "sections", "--template", ROOT / "prompts/P3-write-sheet.md", "--out", out]
    r, data = sh("build_task_sheet.py", *args)
    assert data["ok"] is True, data
    sheet = out.read_text(encoding="utf-8")
    assert "拆开多重嵌套定语" in sheet and "法语长定语" in sheet


def test_revision_uses_last_appendix_boundary_after_body_text():
    d = tmp()
    revision = "一、修订后全文\n正文先解释‘二、附录’这一标题为何出现。\n正文仍在继续。\n二、附录\na. 无\n"
    (d / "revision.md").write_text(revision, encoding="utf-8")
    r, data = sh("validate_revision.py", "--revision", d / "revision.md", "--out", d / "final.md")
    assert r.returncode == 0 and data["ok"] is True
    assert "正文先解释‘二、附录’这一标题为何出现。" in (d / "final.md").read_text(encoding="utf-8")


def test_epub_boundaries_and_multilingual_dehyphenation():
    parser = source_io.BookHTML()
    parser.feed("<ul><li>一</li><li>二</li></ul><table><tr><td>A</td><td>B</td></tr></table>")
    text = parser.text()
    assert "- 一\n- 二" in text and "一\n\n- 二" not in text and "A | B" in text
    samples = {
        "en": "self-\nevident",
        "de": "selbst-\nverständlich",
        "fr": "anti-\nconstitutionnel",
        "es": "inter-\nnacional",
        "ru": "тест-\nирование",
    }
    for lang, sample in samples.items():
        assert "-\n" not in intake_book.clean_book_text(sample, source_lang=lang)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "->", repr(exc)[:300])
    sys.exit(1 if failed else 0)
