# -*- coding: utf-8 -*-
"""test_book_pipeline.py — 验证 book-translator 端到端流程测试（含全书交付质检与概念依赖台账）。"""
import io
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
PYTHON = sys.executable

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tempfile
TEST_WORKSPACE = Path(tempfile.gettempdir()) / "bt-test-book-workspace"


def _gate(stage, ch_dir, env, k=None):
    cmd = [PYTHON, str(SCRIPTS_DIR / "run_stage_checks.py"), "--stage", stage, "--workspace", str(ch_dir)]
    if k:
        cmd += ["--k", str(k)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res.returncode == 0, f"run_stage_checks --stage {stage} 失败: {res.stdout}\n{res.stderr}"


def _write_real_section(ch_dir, points, units, audit, final_text, env):
    """A fixture that carries real artefacts: 12-field points, teaching units, audit rows, final text."""
    sections = ch_dir / "sections"
    (sections / "1-points.md").write_text(points, encoding="utf-8")
    (sections / "1-teaching-units.json").write_text(json.dumps({"units": units}, ensure_ascii=False), encoding="utf-8")
    (sections / "coverage-1.md").write_text(audit, encoding="utf-8")
    (sections / "1-final.md").write_text(final_text, encoding="utf-8")
    (ch_dir / "chapter-final.md").write_text(final_text, encoding="utf-8")
    reports = ch_dir / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "p6-review.md").write_text("人工冷读完成；无未解决问题。", encoding="utf-8")
    (reports / "p6-review.json").write_text(json.dumps({
        "schema_version": 1,
        "review_type": "manual_cold_read",
        "review_completed": True,
        "reviewed_file": "chapter-final.md",
        "report_file": "reports/p6-review.md",
        "reviewed_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        "high_risk_unresolved": [],
        "style_findings": [],
    }, ensure_ascii=False), encoding="utf-8")
    _gate("extract", ch_dir, env, 1)
    _gate("audit", ch_dir, env, 1)
    _gate("chapter", ch_dir, env)


def run():
    print("=== 开始 book-translator 端到端验证测试 ===")

    if TEST_WORKSPACE.exists():
        shutil.rmtree(TEST_WORKSPACE)
    TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)

    # 1. 准备样本测试书籍
    sample_book_path = TEST_WORKSPACE / "sample_book.md"
    sample_text = """# Chapter 1: The Problem of Knowledge

Epistemology has traditionally centered on the definition of propositional knowledge. Since Plato's Theaetetus, philosophers have debated whether justified true belief suffices for knowledge.

In 1963, Edmund Gettier published a landmark paper presenting counterexamples to the tripartite account. These cases demonstrate that one can possess justified true belief purely by coincidence or epistemic luck.

Consequently, modern epistemologists have sought a fourth condition to eliminate the Gettier problem, such as no-false-lemma conditions or safety and sensitivity constraints.

# Chapter 2: The Structure of Justification

Having examined the definition of knowledge, we must now investigate the architecture of epistemic justification itself. How do beliefs support one another?

Foundationalism posits that justification terminates in basic beliefs that require no further inferential support from other beliefs. These foundational beliefs are often claimed to be self-evident or directly grounded in perceptual experience.

In contrast, coherentism rejects the notion of an epistemic foundation, arguing instead that justification arises from the holistic mutual support of a web of beliefs.
"""
    sample_book_path.write_text(sample_text, encoding="utf-8")
    print("1. 样本书籍创建完毕")

    # 2. 运行 intake_book.py
    print("2. 执行 intake_book.py...")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    cmd_intake = [
        PYTHON, str(SCRIPTS_DIR / "intake_book.py"),
        "--input", str(sample_book_path),
        "--workspace", str(TEST_WORKSPACE),
        "--title", "知识与证实论纲",
        "--author", "埃德蒙·盖梯尔",
        "--slug", "knowledge-justification"
    ]
    res_intake = subprocess.run(cmd_intake, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_intake.returncode == 0, f"intake_book.py 失败: {res_intake.stderr}"

    # 验证 intake 产物
    book_json_path = TEST_WORKSPACE / "book.json"
    assert book_json_path.exists(), "book.json 未生成"
    book_info = json.loads(book_json_path.read_text(encoding="utf-8"))
    assert book_info["total_chapters"] == 2, f"章节数不匹配: {book_info['total_chapters']}"
    assert (TEST_WORKSPACE / "chapters/ch01/source-numbered.md").exists(), "ch01/source-numbered.md 未生成"
    assert (TEST_WORKSPACE / "chapters/ch02/source-numbered.md").exists(), "ch02/source-numbered.md 未生成"
    assert (TEST_WORKSPACE / "chapters/ch01/handover-to-ch01.prompt.md").exists(), "第一章启动 Prompt 未生成"
    print("   -> intake_book 验证通过，已成功识别 2 个章节并完成编号！")

    # 3. 模拟完成第一章流水线
    print("3. 模拟完成第一章定稿、反查与术语计划...")
    ch01_dir = TEST_WORKSPACE / "chapters/ch01"

    # 模拟 ch01 outline.json
    outline_data_ch1 = {
        "thesis": "知识不能简单等同于得到证实的真信念，葛梯尔反例揭示了传统三要素定义的致命缺陷。",
        "total_sections": 1,
        "sections": [
            {
                "k": 1,
                "sub_question": "传统知识三要素为何面临危机？",
                "core_content": "分析葛梯尔反例并揭示认识论运气的破坏性。",
                "conclusion": "三要素定义不足以构成知识的充分条件。",
                "chain_role": "核心破题",
                "anchors": [[1, 3]],
                "prohibited": ["基础主义的内涵"],
                "inherits": "无",
                "open_question": "究竟何种证成结构才能彻底排除认识论运气并确立信念合理性？",
                "budget": 800
            }
        ]
    }
    (ch01_dir / "outline.json").write_text(json.dumps(outline_data_ch1, ensure_ascii=False, indent=2), encoding="utf-8")

    # 模拟 ch01 term-plan.json
    term_plan_data_ch1 = {
        "version": 2,
        "terms": [
            {
                "id": "T1",
                "zh": "得到证实的真信念",
                "orig": "justified true belief",
                "level": "核心",
                "gloss": "传统认识论关于知识的古典三要素界定",
                "role": "核心理论对象",
                "example_src": "[P1]",
                "depends_on": [],
                "first_section": 1,
                "confusable_with": [],
                "alias_ban": ["证实信念"]
            },
            {
                "id": "T2",
                "zh": "认识论运气",
                "orig": "epistemic luck",
                "level": "核心",
                "gloss": "因偶然巧合而碰巧为真的认知状态",
                "role": "反例机制",
                "example_src": "[P2]",
                "depends_on": ["T1"],
                "first_section": 1,
                "confusable_with": [],
                "alias_ban": ["认知运气", "碰巧为真"]
            }
        ]
    }
    (ch01_dir / "term-plan.json").write_text(json.dumps(term_plan_data_ch1, ensure_ascii=False, indent=2), encoding="utf-8")

    # 执行 check_term_plan.py 真实质检
    cmd_check_term = [
        PYTHON, str(SCRIPTS_DIR / "check_term_plan.py"),
        "--term-plan", str(ch01_dir / "term-plan.json"),
        "--outline-json", str(ch01_dir / "outline.json"),
        "--numbered", str(ch01_dir / "source-numbered.md")
    ]
    res_term = subprocess.run(cmd_check_term, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_term.returncode == 0, f"check_term_plan.py 校验失败: {res_term.stdout}\n{res_term.stderr}"
    print("   -> check_term_plan.py 质检通过！")

    # 验证单小节 apply_patches 微编辑补丁能力
    test_sec1 = ch01_dir / "sections/1-final.md"
    test_sec1.write_text("认知主体持有真信念。其信念为真纯属巧合。\n", encoding="utf-8")
    test_patch = ch01_dir / "sections/patch-1.md"
    test_patch.write_text("1｜T12｜替换｜其信念为真纯属巧合。｜其信念之所以为真，完全出于某种认识论运气。\n", encoding="utf-8")
    cmd_patch = [
        PYTHON, str(SCRIPTS_DIR / "apply_patches.py"),
        "--patches", str(test_patch),
        "--marked", str(test_sec1),
        "--out", str(test_sec1),
        "--profile", "v2"
    ]
    res_patch = subprocess.run(cmd_patch, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_patch.returncode == 0, f"apply_patches.py 单小节补丁失败: {res_patch.stdout}\n{res_patch.stderr}"
    assert "某种认识论运气" in test_sec1.read_text(encoding="utf-8"), "单小节补丁内容未正确注入"
    print("   -> apply_patches.py 单小节微编辑补丁能力验证通过！")

    final_text_ch1 = """长期以来，哲学界习惯于将知识界定为得到证实的真信念。

在盖梯尔的反例中，认知主体持有得到证实的真信念，但其信念之所以为真，可能纯属认识论运气。

因此，三要素不足以构成知识的充分条件。"""
    points_ch1 = """1.1｜定义｜作者｜知识长期被界定为得到证实的真信念。｜无｜[P2]｜是｜whether justified true belief suffices for knowledge｜得到证实的真信念指传统三要素定义｜断言｜无｜T1:新
1.2｜主张｜作者｜盖梯尔反例表明持有得到证实的真信念可能纯属认识论运气。｜可能｜[P3]｜是｜purely by coincidence or epistemic luck｜认识论运气指碰巧为真｜断言｜无｜T1:回指;T2:新
1.3｜结论｜作者｜因此三要素不足以构成知识的充分条件。｜无｜[P4]｜是｜sought a fourth condition to eliminate the Gettier problem｜无｜断言｜无｜无"""
    units_ch1 = [{"question": "传统知识定义为何出现危机？", "purpose": "让读者看到定义的失效", "method": "先述定义，再引反例，后给结论", "force_note": "反例处保持可能性语气", "point_ids": ["1.1", "1.2", "1.3"]}]
    audit_ch1 = """1.1｜完整｜知识界定为得到证实的真信念｜定义原样保留
1.2｜完整｜可能纯属认识论运气｜保留了可能性限定
1.3｜完整｜三要素不足以构成知识的充分条件｜结论保留
反查｜因此，三要素不足以构成知识的充分条件。｜1.3｜结论
"""
    outline_data_ch1["sections"][0]["anchors"] = [[2, 4]]
    outline_data_ch1["excluded"] = ["P1 章节标题"]
    (ch01_dir / "outline.json").write_text(json.dumps(outline_data_ch1, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_real_section(ch01_dir, points_ch1, units_ch1, audit_ch1, final_text_ch1, env)
    print("   -> 第 1 章定稿与反查报告模拟就绪")

    # 4. 运行 generate_handover.py
    print("4. 执行 generate_handover.py...")
    cmd_handover = [
        PYTHON, str(SCRIPTS_DIR / "generate_handover.py"),
        "--workspace", str(TEST_WORKSPACE),
        "--chapter", "1"
    ]
    res_handover = subprocess.run(cmd_handover, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_handover.returncode == 0, f"generate_handover.py 失败: {res_handover.stderr}"

    # 验证交接文件
    handover_file = ch01_dir / "handover-to-ch02.prompt.md"
    assert handover_file.exists(), "handover-to-ch02.prompt.md 未生成"
    prompt_content = handover_file.read_text(encoding="utf-8")

    # 检查关键承接要素是否包含 locked 状态与概念依赖说明
    assert "得到证实的真信念" in prompt_content, "全局术语未包含在交接 Prompt 中"
    assert "认识论运气" in prompt_content, "全局术语未包含在交接 Prompt 中"
    assert "锁定状态" in prompt_content, "交接 Prompt 缺少锁定状态表头"
    assert "概念依赖" in prompt_content, "交接 Prompt 缺少概念依赖表头"
    assert "已锁定 (locked)" in prompt_content, "交接 Prompt 未标注 locked 状态"
    assert "第 2 章" in prompt_content, "目标章节未正确识别"
    print("   -> generate_handover 验证通过！交接 Prompt 成功融合上一章结尾、遗留悬念与含 locked 状态的全局术语表！")

    # 验证全局术语库中的 locked 与 depends_on 属性
    global_terms = json.loads((TEST_WORKSPACE / "global-term-ledger.json").read_text(encoding="utf-8"))
    assert len(global_terms) >= 2, f"全局术语库未正确累积: {global_terms}"
    assert all(t.get("locked") is True for t in global_terms), "沉淀术语缺少 locked=True 状态"
    assert any(t.get("depends_on") == ["c01:T1"] for t in global_terms), "沉淀术语缺少带章节命名空间的 depends_on 概念依赖"
    assert len({t["uid"] for t in global_terms}) == len(global_terms), "术语 uid 必须全局唯一"
    print(f"   -> global-term-ledger.json 成功沉淀 {len(global_terms)} 个术语（全部带 locked=True 与 depends_on 说明）")

    # 5. 模拟完成第二章定稿、反查与大纲
    print("5. 模拟完成第二章定稿、反查报告与大纲...")
    ch02_dir = TEST_WORKSPACE / "chapters/ch02"

    outline_data_ch2 = {
        "thesis": "证成的结构可分为基础主义与融贯论两大进路，两者分别以自明基石与互证网络应对无穷倒退难题。",
        "total_sections": 1,
        "sections": [
            {
                "k": 1,
                "sub_question": "信念之间的证成关系应当如何架构？",
                "core_content": "对比基础主义的终止原则与融贯论的信念之网。",
                "conclusion": "基础主义与融贯论分别构成了认识论建筑学的两大支柱。",
                "chain_role": "结构展开",
                "anchors": [[4, 6]],
                "prohibited": ["先验知识的心理学起源"],
                "inherits": "得到证实的真信念",
                "open_question": "无",
                "budget": 800
            }
        ]
    }
    (ch02_dir / "outline.json").write_text(json.dumps(outline_data_ch2, ensure_ascii=False, indent=2), encoding="utf-8")

    term_plan_data_ch2 = {
        "version": 2,
        "terms": [
            {
                "id": "T3",
                "zh": "基础主义",
                "orig": "foundationalism",
                "level": "核心",
                "gloss": "主张证实终止于不需要进一步推理支持的基础信念",
                "role": "经典架构进路",
                "example_src": "[P3]",
                "depends_on": ["ledger:得到证实的真信念"],
                "first_section": 1,
                "confusable_with": [],
                "alias_ban": ["基石论"]
            },
            {
                "id": "T4",
                "zh": "融贯论",
                "orig": "coherentism",
                "level": "核心",
                "gloss": "主张证实源自信念之网的整体互证支持",
                "role": "竞争架构进路",
                "example_src": "[P4]",
                "depends_on": ["ledger:得到证实的真信念"],
                "first_section": 1,
                "confusable_with": [],
                "alias_ban": ["自洽论"]
            }
        ]
    }
    (ch02_dir / "term-plan.json").write_text(json.dumps(term_plan_data_ch2, ensure_ascii=False, indent=2), encoding="utf-8")

    outline_data_ch2["sections"][0]["anchors"] = [[2, 4]]
    outline_data_ch2["sections"][0]["budget"] = 100
    outline_data_ch1["sections"][0]["budget"] = 120
    outline_data_ch2["excluded"] = ["P1 章节标题"]
    (ch02_dir / "outline.json").write_text(json.dumps(outline_data_ch2, ensure_ascii=False, indent=2), encoding="utf-8")
    final_text_ch2 = """基础主义主张，证成终止于无需其他信念进一步推理支持的基础信念，借此阻断无穷倒退的追问，使整个证成结构得以收束。

融贯论则否认存在认识论基础，认为证成来自信念之网的整体互相支持，而不是来自某个终点。"""
    points_ch2 = """1.1｜主张｜作者｜基础主义主张证成终止于无需其他信念进一步推理支持的基础信念。｜无｜[P3]｜是｜justification terminates in basic beliefs that require no further inferential support｜无｜断言｜无｜T3:新
1.2｜主张｜作者｜融贯论否认存在认识论基础，认为证成来自信念之网的整体互相支持。｜无｜[P4]｜是｜justification arises from the holistic mutual support of a web of beliefs｜无｜断言｜无｜T4:新"""
    units_ch2 = [{"question": "证成关系应如何架构？", "purpose": "对比两种结构", "method": "并列呈现", "force_note": "均为作者断言", "point_ids": ["1.1", "1.2"]}]
    audit_ch2 = """1.1｜完整｜证成终止于无需其他信念进一步推理支持的基础信念｜保留
1.2｜完整｜认为证成来自信念之网的整体互相支持｜保留
反查｜融贯论则否认存在认识论基础，认为证成来自信念之网的整体互相支持，而不是来自某个终点。｜1.2｜结论
"""
    _write_real_section(ch02_dir, points_ch2, units_ch2, audit_ch2, final_text_ch2, env)

    # 运行 generate_handover.py 沉淀第二章术语
    cmd_handover2 = [
        PYTHON, str(SCRIPTS_DIR / "generate_handover.py"),
        "--workspace", str(TEST_WORKSPACE),
        "--chapter", "2"
    ]
    res_handover2 = subprocess.run(cmd_handover2, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_handover2.returncode == 0, f"第2章 generate_handover.py 失败: {res_handover2.stderr}"
    print("   -> 第 2 章完成并沉淀全局台账（全书所有章节均已处理完成）")

    # 6. 验证全书整体质检能力 (--check)
    print("6. 执行 merge_book.py --check 独立质检模式...")
    cmd_check = [
        PYTHON, str(SCRIPTS_DIR / "merge_book.py"),
        "--workspace", str(TEST_WORKSPACE),
        "--check"
    ]
    res_check = subprocess.run(cmd_check, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_check.returncode == 0, f"merge_book.py --check 质检失败: {res_check.stdout}\n{res_check.stderr}"
    check_payload = json.loads(res_check.stdout)
    assert check_payload["ok"] is True, f"质检未能通过: {check_payload}"
    assert check_payload["violation_count"] == 0, f"存在未预期违规: {check_payload['violations']}"
    print("   -> merge_book.py --check 自动化整体质检 100% 绿色通过 (0 违规)！")

    # 7. 验证 run_stage_checks.py --stage deliver
    print("7. 执行 run_stage_checks.py --stage deliver 交付质检...")
    cmd_stage_deliver = [
        PYTHON, str(SCRIPTS_DIR / "run_stage_checks.py"),
        "--stage", "deliver",
        "--workspace", str(TEST_WORKSPACE)
    ]
    res_stage_deliver = subprocess.run(cmd_stage_deliver, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_stage_deliver.returncode == 0, f"run_stage_checks deliver 阶段失败: {res_stage_deliver.stdout}\n{res_stage_deliver.stderr}"
    print("   -> run_stage_checks.py --stage deliver 交付质检阶段验证通过！")

    # 8. 运行 merge_book.py --strict 汇编全书
    print("8. 执行 merge_book.py --strict 汇编全书...")
    cmd_merge = [
        PYTHON, str(SCRIPTS_DIR / "merge_book.py"),
        "--workspace", str(TEST_WORKSPACE),
        "--strict"
    ]
    res_merge = subprocess.run(cmd_merge, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res_merge.returncode == 0, f"merge_book.py --strict 失败: {res_merge.stdout}\n{res_merge.stderr}"

    out_md = TEST_WORKSPACE / "output/knowledge-justification-全文研读稿.md"
    out_docx = TEST_WORKSPACE / "output/knowledge-justification-全文研读稿.docx"
    out_glossary = TEST_WORKSPACE / "output/knowledge-justification-全书术语与概念台账.md"
    out_report = TEST_WORKSPACE / "output/knowledge-justification-全书质检报告.json"

    assert out_md.exists(), "全书 Markdown 交付物未生成"
    assert out_docx.exists(), "全书 DOCX 交付物未生成"
    assert out_glossary.exists(), "全书术语台账未生成"
    assert out_report.exists(), "全书质检报告未生成"

    # 详细校验全书术语与概念台账的内容规范性
    glossary_content = out_glossary.read_text(encoding="utf-8")
    assert "锁定状态" in glossary_content, "术语台账缺少锁定状态列"
    assert "概念依赖 (depends_on)" in glossary_content, "术语台账缺少概念依赖列"
    assert "已锁定 (locked)" in glossary_content, "术语台账未包含已锁定状态标识"
    assert "## 二、概念依赖拓扑" in glossary_content, "术语台账缺少概念依赖拓扑章节"
    assert "第 0 层" in glossary_content and "第 1 层" in glossary_content, "术语台账缺少 Kahn 分层"
    assert "```mermaid" in glossary_content, "术语台账缺少 Mermaid 依赖图"
    assert "得到证实的真信念" in glossary_content and "基础主义" in glossary_content, "跨章沉淀术语不完整"

    # 校验质检报告
    report_data = json.loads(out_report.read_text(encoding="utf-8"))
    assert report_data["ok"] is True, f"交付质检报告未通过: {report_data}"
    assert len(report_data["violations"]) == 0, f"质检报告违规项非空: {report_data['violations']}"

    print("   -> 全书 Markdown 汇编成功！大小:", out_md.stat().st_size, "字节")
    print("   -> 全书出版级 DOCX 排版生成成功！大小:", out_docx.stat().st_size, "字节")
    print("   -> 全书术语与概念台账规范验证通过！大小:", out_glossary.stat().st_size, "字节")
    print("   -> 全书整体质检报告验证通过！")

    print("\n[OK] === 所有流水线验证测试 100% 全部通过！ ===\n")
    return True


if __name__ == "__main__":
    run()

