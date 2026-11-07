# -*- coding: utf-8 -*-
"""test_build_task_sheet.py — 验证任务单构建器 build_task_sheet.py 的安全阻断与特性注入。"""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
PROMPTS_DIR = SKILL_DIR / "prompts"
PYTHON = sys.executable

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tempfile
TEST_DIR = Path(tempfile.gettempdir()) / "bt-test-build-task-sheet"


def setup_workspace():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    sections_dir = TEST_DIR / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    # 1. 编号源文
    numbered_file = TEST_DIR / "source-numbered.md"
    numbered_file.write_text(
        "[P1] Knowledge has traditionally been defined as justified true belief.\n\n"
        "[P2] Gettier demonstrated that this tripartite account fails.\n",
        encoding="utf-8"
    )

    # 2. 章节大纲
    outline_data = {
        "thesis": "知识定义与证成问题全书考察",
        "total_sections": 2,
        "sections": [
            {
                "k": 1,
                "sub_question": "传统知识三要素为何面临危机？",
                "core_content": "分析葛梯尔反例并揭示认识论运气的破坏性。",
                "conclusion": "三要素定义不足以构成知识的充分条件。",
                "chain_role": "核心破题",
                "anchors": [[1, 2]],
                "prohibited": ["基础主义的内涵"],
                "inherits": "无",
                "open_question": "何种证成结构才能排除运气？",
                "budget": 800
            },
            {
                "k": 2,
                "sub_question": "基础主义能否提供终极确证？",
                "core_content": "探讨基础主义的认知结构。",
                "conclusion": "基础主义面临基础信念如何辩护的挑战。",
                "chain_role": "推进论证",
                "anchors": [[2, 2]],
                "prohibited": ["融贯论的细节"],
                "inherits": "何种证成结构才能排除运气？",
                "open_question": "融贯论是否是可行替代？",
                "budget": 1000
            }
        ]
    }
    (TEST_DIR / "outline.json").write_text(json.dumps(outline_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. 承重清单 points.md
    points_content = (
        "1.1｜定义｜作者｜知识传统上被界定为得到证实的真信念。｜无｜[P1]｜是｜justified true belief｜认识论核心三要素｜断言｜无｜T1:新\n"
        "1.2｜反例｜作者｜盖梯尔反例证明了这一三要素定义的破产。｜无｜[P2]｜是｜this tripartite account fails｜盖梯尔难题｜断言｜无｜T2:新\n"
    )
    (TEST_DIR / "1-points.md").write_text(points_content, encoding="utf-8")

    # 4. 术语计划 term-plan.json，包含顶层 user_banned 与词条级 user_banned
    term_plan_data = {
        "version": 2,
        "user_banned": ["绝对真理", "直觉即证实"],
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
                "alias_ban": ["证实信念"],
                "user_banned": ["真理信念"]
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
                "alias_ban": ["偶然运气"]
            }
        ]
    }
    (TEST_DIR / "term-plan.json").write_text(json.dumps(term_plan_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. 全书全局术语库 global-term-ledger.json
    global_terms_data = [
        {
            "id": "GT1",
            "zh": "证成结构",
            "orig": "justification structure",
            "gloss": "信念之间相互支持的组织体系",
            "locked": True
        }
    ]
    (TEST_DIR / "global-term-ledger.json").write_text(json.dumps(global_terms_data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_leak_prevention_write_mode():
    """测试 1：write 模式下如果模板包含【源材料】占位符，抛错阻断。"""
    print("--- 测试 1: write 模式下【源材料】防泄漏阻断测试 ---")
    setup_workspace()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    cmd = [
        PYTHON, str(SCRIPTS_DIR / "build_task_sheet.py"),
        "--k", "1",
        "--outline-json", str(TEST_DIR / "outline.json"),
        "--sections-dir", str(TEST_DIR / "sections"),
        "--template", str(PROMPTS_DIR / "P3-extract-sheet.md"),  # 错误地使用了包含【源材料】的抽取模板
        "--out", str(TEST_DIR / "1-task-wrong.md"),
        "--mode", "write",
        "--points", str(TEST_DIR / "1-points.md"),
        "--term-plan", str(TEST_DIR / "term-plan.json")
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res.returncode != 0, f"预期失败但成功退出: {res.stdout}"
    assert "write template contains source-material field" in res.stdout, f"未触发指定错误提示: {res.stdout}"
    assert not (TEST_DIR / "1-task-wrong.md").exists(), "发生违规时禁止生成任务单文件"
    print("   -> 成功拦截：包含【源材料】占位符的写作模板被正确阻断，未生成任何任务单！")


def test_write_mode_with_user_banned_and_book_continuity():
    """测试 2：write 模式下正常构建任务单，验证 user_banned 合入、跨章结尾承接、全局术语合入与物理隔绝。"""
    print("--- 测试 2: 写作任务单构建与特性合入测试 ---")
    setup_workspace()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    cmd = [
        PYTHON, str(SCRIPTS_DIR / "build_task_sheet.py"),
        "--k", "1",
        "--outline-json", str(TEST_DIR / "outline.json"),
        "--sections-dir", str(TEST_DIR / "sections"),
        "--template", str(PROMPTS_DIR / "P3-write-sheet.md"),
        "--out", str(TEST_DIR / "1-task-write.md"),
        "--mode", "write",
        "--points", str(TEST_DIR / "1-points.md"),
        "--term-plan", str(TEST_DIR / "term-plan.json"),
        "--global-terms", str(TEST_DIR / "global-term-ledger.json"),
        "--prev-chapter-tail", "导言尾段：认识论的探索由此全面展开。"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res.returncode == 0, f"构建失败: {res.stdout}\n{res.stderr}"
    assert (TEST_DIR / "1-task-write.md").exists(), "写作任务单未生成"

    sheet_text = (TEST_DIR / "1-task-write.md").read_text(encoding="utf-8")

    # 1. 验证【禁写清单】中合入了 outline.prohibited 以及顶层和术语级 user_banned
    assert "基础主义的内涵" in sheet_text, "大纲禁写项未合入"
    assert "绝对真理" in sheet_text, "顶层 user_banned 未合入"
    assert "直觉即证实" in sheet_text, "顶层 user_banned 未合入"
    assert "真理信念" in sheet_text, "术语级 user_banned 未合入"
    print("   -> 禁写清单合入验证通过：大纲 prohibited + 顶层 user_banned + 词条级 user_banned 完整融合！")

    # 2. 验证跨章承接 --prev-chapter-tail 成功注入上一节结尾
    assert "导言尾段：认识论的探索由此全面展开。" in sheet_text, "上一章结尾未注入上一节结尾"
    assert "优先直接陈述" in sheet_text and "否定范围" in sheet_text, "写作偏好未进入实际任务单"
    print("   -> 跨章首尾衔接验证通过：--prev-chapter-tail 成功作为首节上一节结尾注入！")

    # 3. 验证全局术语合入
    assert "证成结构" in sheet_text or "justification structure" in sheet_text, "全局术语库未合入已定术语表"
    print("   -> 全书全局术语库验证通过：--global-terms 成功合入！")

    # 4. 验证源材料物理隔绝
    assert "【源材料】" not in sheet_text, "任务单中出现了【源材料】字段"
    assert "Knowledge has traditionally been defined" not in sheet_text, "源文英文句子泄漏给了写作者"
    print("   -> 物理隔绝防翻译腔验证通过：任务单无【源材料】且无英文源文句！")


def test_extract_mode():
    """测试 3：extract 模式正常运行，生成含源材料的任务单。"""
    print("--- 测试 3: extract 模式任务单构建测试 ---")
    setup_workspace()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    cmd = [
        PYTHON, str(SCRIPTS_DIR / "build_task_sheet.py"),
        "--k", "1",
        "--outline-json", str(TEST_DIR / "outline.json"),
        "--numbered", str(TEST_DIR / "source-numbered.md"),
        "--sections-dir", str(TEST_DIR / "sections"),
        "--template", str(PROMPTS_DIR / "P3-extract-sheet.md"),
        "--out", str(TEST_DIR / "1-task-extract.md"),
        "--mode", "extract",
        "--term-plan", str(TEST_DIR / "term-plan.json")
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    assert res.returncode == 0, f"抽取任务单构建失败: {res.stdout}\n{res.stderr}"
    assert (TEST_DIR / "1-task-extract.md").exists(), "抽取任务单未生成"

    sheet_text = (TEST_DIR / "1-task-extract.md").read_text(encoding="utf-8")
    assert "【源材料】" in sheet_text, "抽取任务单中缺少【源材料】"
    assert "[P1] Knowledge has traditionally been defined" in sheet_text, "编号源文未正确抽取"
    print("   -> 抽取任务单验证通过：正确包含编号源材料！")


def run():
    print("=== 开始 build_task_sheet.py 专项测试 ===")
    test_leak_prevention_write_mode()
    test_write_mode_with_user_banned_and_book_continuity()
    test_extract_mode()
    print("\n[OK] === build_task_sheet.py 所有专项测试 100% 全部通过！ ===\n")
    return True


if __name__ == "__main__":
    run()

