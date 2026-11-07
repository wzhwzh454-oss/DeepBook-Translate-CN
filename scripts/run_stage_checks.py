# -*- coding: utf-8 -*-
"""run_stage_checks.py — 单章各阶段质量检查统一调度器。

支持阶段：
  --stage extract: 检查本章/本节意义抽取清单 (points)、讲解单元 (teaching units) 与术语计划
  --stage draft:   检查本节中文初稿格式规范、篇幅与可读性
  --stage audit:   检查本节覆盖核验报告 (coverage)、力度/模态反查 (force) 与术语一致性
  --stage chapter: 检查整章拼合定稿 (chapter-final.md)、全文覆盖与连贯性
  --stage deliver: 检查最终交付文件 (DOCX / Markdown) 一致性
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from check_force import check_force
from check_points import parse_points
from reader_v3 import validate_teaching_units
from bt_common import resolve_chapter_final, sha256_text, english_leaks, sha256_file
from language import source_language_leaks
from workspace_config import load_config, source_language
import re
import textutil
import zipfile
import xml.etree.ElementTree as ET


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Checks:
    def __init__(self, workspace, report):
        self.workspace = workspace
        self.report = report
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.results = []
        self.meta = {}

    def record(self, name, result, section=None):
        self.results.append({"check": name, "section": section, "result": result})
        return result

    def call(self, name, script, arguments, section=None):
        command = [sys.executable, str(script), *[str(value) for value in arguments]]
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        )
        try:
            result = json.loads(completed.stdout)
            if not isinstance(result, dict):
                raise ValueError("checker did not return a JSON object")
        except (ValueError, TypeError) as error:
            diagnostic = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else str(error)
            result = {"ok": False, "violations": [f"{name} 执行失败: {diagnostic}"], "stdout": completed.stdout}

        if completed.returncode or result.get("ok") is not True:
            result["ok"] = False
            if not result.get("violations") and type(result.get("violations")) is not int:
                result["violations"] = [f"checker 退出码 {completed.returncode}"]
        result["command"] = command
        result["returncode"] = completed.returncode
        if completed.stderr:
            result["stderr"] = completed.stderr
        return self.record(name, result, section)

    def failure(self, item):
        result = item["result"]
        issues = result.get("violations", [])
        report = result.get("report")
        if isinstance(issues, list):
            count, sample = len(issues), issues[:3]
        elif isinstance(issues, int) and issues >= 0:
            count = issues
            sample = [f"见详细报告: {report}"] if report else ["未提供详细样本"]
        else:
            count, sample = 0, ["返回值格式异常"]
        failure = {"check": item["check"], "section": item["section"], "count": count, "sample": sample}
        if report:
            failure["report"] = str(report)
        return failure

    def save(self, stage):
        paths = [self.workspace / name for name in ("source-numbered.md", "outline.json", "term-plan.json", "chapter-final.md")]
        paths.extend(self.workspace / name for name in ("reports/p6-review.md", "reports/p6-review.json"))
        section_dir = self.workspace / "sections"
        if section_dir.exists():
            paths.extend(p for p in section_dir.iterdir() if p.is_file() and p.suffix in (".md", ".json"))
        self.meta["input_sha256"] = {str(p.resolve()): sha256_file(p) for p in paths if p.is_file()}
        failures = [item for item in self.results if item["result"].get("ok") is not True]
        payload = {
            "ok": not failures,
            "stage": stage,
            "checks": self.results,
            "meta": self.meta,
            "scope": "机械阶段检查；真实质量责任仍在细读与回源核验"
        }
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        previews = [{**f, "sample": [str(x)[:200] for x in f["sample"][:2]]} for f in (self.failure(it) for it in failures[:6])]
        summary = {
            "ok": payload["ok"],
            "stage": stage,
            "checks": len(self.results),
            "report": str(self.report),
            "failures": previews,
            "failure_count": len(failures)
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if payload["ok"] else 1


def docx_structure_problems(path, expected_chapters):
    """Open the .docx package and check what 'publication grade' actually requires."""
    problems = []
    if not zipfile.is_zipfile(path):
        return ['not a valid .docx (zip) package']
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        document = package.read('word/document.xml').decode('utf-8', 'replace')
        styles_xml = package.read('word/styles.xml').decode('utf-8')
        footers = ''.join(package.read(n).decode('utf-8', 'replace') for n in names if n.startswith('word/footer'))
        settings = package.read('word/settings.xml').decode('utf-8', 'replace') if 'word/settings.xml' in names else ''
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    attribute = '{' + ns['w'] + '}'
    heading_ids = set()
    for style in ET.fromstring(styles_xml).findall('w:style', ns):
        name = style.find('w:name', ns)
        if name is not None and re.sub(r'\s+', '', name.get(attribute + 'val', '')).lower() in ('heading1', '标题1'):
            heading_ids.add(style.get(attribute + 'styleId'))
    actual_headings = sum(node.get(attribute + 'val') in heading_ids for node in ET.fromstring(document).findall('.//w:pPr/w:pStyle', ns))
    if actual_headings < expected_chapters:
        problems.append('chapter titles are not real Heading 1 paragraphs (no navigation pane / TOC source)')
    if 'TOC \\o' not in document and 'TOC \\o' not in settings:
        problems.append('no TOC field: the table of contents is hand-typed text without page numbers')
    if 'PAGE' not in footers:
        problems.append('footer has no PAGE field (no page numbers)')
    if not re.search(r'<w:pgSz [^>]*w:w="11906"', document):
        problems.append('page size is not A4')
    return problems


def chapter_gates(workspace, sections, checks, final_path):
    """What the old chapter stage never looked at: the integrated text itself."""
    from check_coverage import check_coverage
    from check_terms import faithful_paragraphs, term_variant_report
    text = final_path.read_text(encoding="utf-8")
    violations, advisories = [], []
    section_total = 0
    for section in sections:
        number = section["k"]
        path = workspace / "sections" / f"{number}-final.md"
        if not path.exists():
            violations.append(f"section {number}: {number}-final.md missing; the chapter would be truncated")
        else:
            section_total += textutil.cjk_count(path.read_text(encoding="utf-8"))
    total = textutil.cjk_count(text)
    if section_total and total < 0.85 * section_total:
        violations.append(f"chapter-final has {total} CJK but its sections total {section_total}: integration lost >15% of the text")
    for pattern, label in ((r"【第\d+节】", "section marker"), (r"\{\{[A-Z0-9_]+\}\}", "unrendered template variable"), (r"待补充|待定稿|TODO", "placeholder")):
        match = re.search(pattern, text)
        if match:
            violations.append(f"residual {label}: {match.group(0)!r}")
    plan_path = workspace / "term-plan.json"
    plan = read_json(plan_path) if plan_path.exists() else None
    allow = [t.get("orig") for t in (plan or {}).get("terms", []) if isinstance(t, dict)]
    for snippet in source_language_leaks("\n\n".join(faithful_paragraphs(text)), allow, min_words=8, source_lang=source_language(workspace))[:5]:
        advisories.append(f"possible untranslated source text in final text: {snippet!r}")
    if plan:
        report = term_variant_report(text, plan)
        violations.extend(f"integrated text: {issue}" for issue in report["violations"])
        advisories.extend(f"integrated text: {issue}" for issue in report["advisories"][:20])
    for section in sections:
        number = section["k"]
        points_path = workspace / "sections" / f"{number}-points.md"
        audit_path = workspace / "sections" / f"coverage-{number}.md"
        if not (points_path.exists() and audit_path.exists()):
            violations.append(f"section {number}: points/coverage record missing; audit chain is broken")
            continue
        points, _ = parse_points(points_path.read_text(encoding="utf-8"))
        after = check_coverage(text, points, audit_path.read_text(encoding="utf-8"), min_rate=load_config(workspace)["translation"].get("coverage_min_rate", 1.0))
        for issue in after["violations"]:
            if "reverse evidence absent" in issue:  # P5 may legitimately delete seam sentences
                advisories.append(f"section {number}: {issue}")
            else:
                violations.append(f"section {number}: after integration {issue}; re-run P8 for this section")
    return {"ok": not violations, "violations": violations, "advisories": advisories,
            "metrics": {"chapter_cjk": total, "sections_cjk": section_total}}


def stage_checks(arguments, checks):
    workspace = arguments.workspace
    config = load_config(workspace)

    # 交付阶段 (deliver) 优先处理（支持全书工作区或章节工作区）
    if arguments.stage == "deliver":
        book_file = workspace / "book.json"
        if not book_file.exists() and (workspace.parent / "book.json").exists():
            workspace_root = workspace.parent
            book_file = workspace_root / "book.json"
        else:
            workspace_root = workspace

        if book_file.exists():
            checks.call("book-integrity", ROOT / "merge_book.py", ["--workspace", workspace_root, "--check"])
        if arguments.docx:
            if not arguments.docx.exists():
                checks.record("deliver-docx", {"ok": False, "violations": [f"未找到指定的 DOCX 文件: {arguments.docx}"]})
            else:
                expected = len(read_json(book_file).get("chapters", [])) if book_file.exists() else 1
                problems = docx_structure_problems(arguments.docx, expected)
                checks.record("deliver-docx", {"ok": not problems, "violations": problems})
        elif not book_file.exists():
            checks.record("deliver-target", {"ok": False, "violations": ["未找到 book.json 且未指定 --docx，无法执行交付检查"]})
        return

    outline_path = workspace / "outline.json"
    if not outline_path.exists():
        checks.record("outline-missing", {"ok": False, "violations": [f"未找到 outline.json: {outline_path}"]})
        return

    outline = read_json(outline_path)
    sections = outline.get("sections", [])
    known = {section["k"] for section in sections}
    selected = set(arguments.k or known)
    if not selected <= known:
        raise ValueError(f"未知的小节序号: {sorted(selected - known)}")

    section_records = [sec for sec in sections if sec["k"] in selected]
    section_directory = workspace / "sections"
    terms = workspace / "term-plan.json"
    numbered = workspace / "source-numbered.md"
    min_rate = config["translation"].get("coverage_min_rate", 0.95)
    ledger_file = workspace.resolve().parent.parent / "global-term-ledger.json"
    ledger_args = ["--global-terms", ledger_file] if workspace.resolve().parent.name == "chapters" and ledger_file.exists() else []
    if not terms.exists():  # v2.0 silently skipped every terminology gate when this file was absent
        checks.record("term-plan-missing", {"ok": False, "violations": ["缺少 term-plan.json：术语门禁不能被静默跳过"]})

    # 1. 抽取阶段 (extract)
    if arguments.stage == "extract":
        if terms.exists():
            term_args = ["--term-plan", terms, "--outline-json", outline_path, "--numbered", numbered]
            ledger_path = workspace.resolve().parent.parent / "global-term-ledger.json"
            if workspace.resolve().parent.name == "chapters" and ledger_path.exists():
                term_args += ["--global-terms", ledger_path]  # v2.0 never passed the ledger, so locked drift was never checked
            checks.call("term-plan", ROOT / "check_term_plan.py", term_args)
        for section in section_records:
            number = section["k"]
            points_path = section_directory / f"{number}-points.md"
            if points_path.exists():
                params = ["--points", points_path, "--numbered", numbered, "--outline-json", outline_path, "--k", number, "--schema-version", 2]
                if terms.exists():
                    params.extend(["--term-plan", terms])
                checked = checks.call("points", ROOT / "check_points.py", params, number)
                points = checked.get("points", [])
                tu_path = section_directory / f"{number}-teaching-units.json"
                if tu_path.exists():
                    units = read_json(tu_path).get("units", [])
                    violations = validate_teaching_units(units, points)
                    checks.record("teaching-units", {"ok": not violations, "violations": violations}, number)
                else:
                    checks.record("teaching-units-missing", {"ok": False, "violations": [f"缺少 {tu_path.name}：写作任务单没有讲解单元将退化为逐条造句"]}, number)
            else:
                checks.record("points-missing", {"ok": False, "violations": [f"缺少 {points_path.name}"]}, number)

    # 2. 中文初稿阶段 (draft)
    elif arguments.stage == "draft":
        for section in section_records:
            number = section["k"]
            text_path = section_directory / f"{number}-final.md"
            if not text_path.exists():
                text_path = section_directory / f"{number}-revision.md"
            if text_path.exists():
                budget = section.get("budget", 0)
                checks.call("draft", ROOT / "check_draft.py", ["--draft", text_path, "--profile", "v2", "--budget", budget], number)
                points_path = section_directory / f"{number}-points.md"
                readability_args = ["--text", text_path, "--candidates"]
                if points_path.exists():
                    readability_args.extend(["--points", points_path])
                checks.call("readability", ROOT / "check_readability.py", readability_args, number)
                if terms.exists():
                    checks.call("terms", ROOT / "check_terms.py", ["--text", text_path, "--term-plan", terms, "--k", number, "--sections-dir", section_directory] + ledger_args, number)
            else:
                checks.record("draft-missing", {"ok": False, "violations": [f"缺少草稿文件: {text_path.name}"]}, number)

    # 3. 覆盖率核验阶段 (audit)
    elif arguments.stage == "audit":
        for section in section_records:
            number = section["k"]
            text_path = section_directory / f"{number}-final.md"
            audit_path = section_directory / f"coverage-{number}.md"
            if text_path.exists() and audit_path.exists():
                coverage_path = checks.report.parent / f"coverage-{number}.json"
                checks.call("coverage", ROOT / "check_coverage.py", [
                    "--article", text_path,
                    "--points-dir", section_directory,
                    "--audit", audit_path,
                    "--k", number,
                    "--min-rate", min_rate,
                    "--out-json", coverage_path
                ], number)
                checks.call("force", ROOT / "check_force.py", [
                    "--text", text_path,
                    "--points-dir", section_directory,
                    "--coverage-json", coverage_path,
                    "--require-reverse",
                    "--out-json", checks.report.parent / f"force-{number}.json"
                ], number)
                if terms.exists():
                    checks.call("terms", ROOT / "check_terms.py", ["--text", text_path, "--term-plan", terms, "--k", number, "--sections-dir", section_directory] + ledger_args, number)
            else:
                checks.record("audit-missing", {"ok": False, "violations": [f"缺少 final 或 coverage 报告文件"]}, number)

    # 4. 整章整合阶段 (chapter)
    elif arguments.stage == "chapter":
        chapter_final, final_problems = resolve_chapter_final(workspace)
        if final_problems and chapter_final is not None:
            checks.record("chapter-final-ambiguous", {"ok": False, "violations": final_problems})
        if chapter_final is not None:
            checks.meta["final_sha256"] = sha256_text(chapter_final.read_text(encoding="utf-8"))
            checks.meta["final_file"] = chapter_final.name
            from p6_review import review_state
            checks.record("p6-manual-cold-read", review_state(workspace, chapter_final))
            checks.call("punctuation-budget", ROOT / "check_punctuation_budget.py", [
                "--source", workspace / "source-numbered.md",
                "--translation", chapter_final,
            ])
            checks.record("chapter-integrity", chapter_gates(workspace, section_records if arguments.k else sections, checks, chapter_final))
            total_budget = sum(sec.get("budget", 0) for sec in sections) or 4000
            floor = int(total_budget * 0.7)
            ceiling = int(total_budget * 1.5)
            checks.call("check-merged", ROOT / "check_merged.py", [
                "--merged", chapter_final,
                "--floor", floor,
                "--ceiling", ceiling,
                "--tolerance", 500
            ])
        else:
            checks.record("chapter-final-missing", {"ok": False, "violations": ["缺少 chapter-final.md 定稿文稿"]})



def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("extract", "draft", "audit", "chapter", "deliver"), required=True)
    parser.add_argument("--workspace", type=Path, required=True, help="章节工作区目录（如 chapters/ch01）")
    parser.add_argument("--k", type=int, action="append", help="指定检查的小节号")
    parser.add_argument("--docx", type=Path, help="交付 docx 路径")
    parser.add_argument("--out-json", type=Path, help="自定义输出报告路径")
    arguments = parser.parse_args(argv)

    workspace = arguments.workspace.resolve()
    report = arguments.out_json or (workspace / "reports" / f"{arguments.stage}-checks.json")
    checks = Checks(workspace, report)

    try:
        stage_checks(arguments, checks)
    except Exception as error:
        checks.record("stage-exception", {"ok": False, "violations": [str(error)]})

    return checks.save(arguments.stage)


if __name__ == "__main__":
    sys.exit(main())

