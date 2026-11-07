import argparse
import json
import re
from collections import Counter
from pathlib import Path

from check_points import parse_points
from check_terms import faithful_paragraphs
import textutil
from bt_common import match_fold
from operators import operator_parity


STATUSES = {"完整", "弱化", "改义", "缺失"}


def _evidence_context(faithful_text, evidence):
    """Whole sentence(s) of the article that contain the evidence span."""
    spans = textutil.find_norm_spans(faithful_text, evidence)
    if not spans:
        return evidence
    start, stop = spans[0]
    parts = [faithful_text[a:b] for a, b in textutil.split_sentences_spans(faithful_text) if a < stop and b > start]
    return ''.join(parts) or evidence


def _bigrams(text):
    chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    return {a + b for a, b in zip(chars, chars[1:])}


def check_coverage(article, points, audit, min_rate=0.95, operator_mode='advisory'):
    required = {point["id"]: point for point in points if point["bearing"] == "是"}
    violations = []
    entries = {}
    extraction_issues = []
    reverse_entries = []
    all_ids = {point["id"] for point in points}
    faithful_text = '\n\n'.join(faithful_paragraphs(article))
    normalized = textutil.compact(faithful_text)
    advisories = []
    for number, line in enumerate(audit.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [cell.strip() for cell in line.split("｜")]
        if cells[0] == "反查":
            if len(cells) != 4 or cells[3] not in {"结论", "小结", "过渡", "导航"}:
                violations.append(f"line {number}: invalid reverse audit")
                continue
            ids = [] if cells[2] == "无" else [value.strip() for value in re.split(r"[;；,，]", cells[2]) if value.strip()]
            reverse_entries.append({"evidence": cells[1], "point_ids": ids, "kind": cells[3]})
            if not cells[1] or textutil.compact(cells[1]) not in normalized:
                violations.append(f"line {number}: reverse evidence absent")
            from check_force import pure_navigation
            navigation = cells[3] in {'过渡', '导航'} and pure_navigation(cells[1])
            if (not ids and not navigation) or any(point_id not in all_ids for point_id in ids):
                violations.append(f"line {number}: unsupported/unknown reverse source")
            continue
        if cells[0] in {"漏抽", "失真"}:
            if len(cells) < 3:
                violations.append(f"line {number}: malformed extraction issue")
            extraction_issues.append(line)
            violations.append(f"line {number}: {cells[0]} requires re-extraction before writing")
            continue
        if len(cells) != 4 or cells[1] not in STATUSES:
            violations.append(f"line {number}: invalid audit row")
            continue
        point_id, status, evidence, explanation = cells
        if point_id not in required:
            violations.append(f"line {number}: unknown/non-bearing id {point_id}")
            continue
        if point_id in entries:
            violations.append(f"line {number}: duplicate id {point_id}")
            continue
        if status in {"完整", "弱化"} and (not textutil.compact(evidence) or textutil.compact(evidence) not in normalized
                                       or len(match_fold(evidence)[0]) < 8):
            status = "证据无效"
        entries[point_id] = {"id": point_id, "status": status, "evidence": evidence, "explanation": explanation}
    for point_id in required.keys() - entries.keys():
        entries[point_id] = {"id": point_id, "status": "缺失", "evidence": "", "explanation": "审计漏项"}
    operator_issues = []
    shared = Counter(textutil.compact(e['evidence']) for e in entries.values() if e['status'] in {'完整', '弱化'} and e['evidence'])
    for text, times in shared.items():
        if times > 3:
            advisories.append(f"one evidence span is claimed by {times} different points; verify each proposition separately: {text[:40]}")
    for entry in entries.values():
        if entry['status'] not in {'完整', '弱化'} or entry['id'] not in required:
            continue
        point = required[entry['id']]
        context = _evidence_context(faithful_text, entry['evidence'])
        found = operator_parity(point.get('statement', ''), point.get('qualifiers', ''), context)
        if found:
            operator_issues.append({'id': entry['id'], 'issues': found})
            for issue in found:
                hard = issue.startswith('hard: ')
                if hard or operator_mode == 'strict':
                    violations.append(f"{entry['id']}: {issue.removeprefix('hard: ').removeprefix('advisory: ')}")
                elif operator_mode == 'advisory':
                    advisories.append(f"{entry['id']}: {issue.removeprefix('advisory: ')}")
        if _bigrams(point.get('statement', '')) and not (_bigrams(point.get('statement', '')) & _bigrams(context)):
            advisories.append(f"{entry['id']}: evidence shares no character bigram with the proposition; check it really supports it")
    counts = Counter(entry["status"] for entry in entries.values())
    total = len(required)
    rate = (counts["完整"] + 0.5 * counts["弱化"]) / total if total else 0
    if not total:
        violations.append("no bearing points; coverage is undefined")
    if rate < min_rate:
        violations.append(f"coverage {rate:.1%} below {min_rate:.1%}")
    repair = [entry for entry in entries.values() if entry["status"] != "完整"]
    for entry in repair:
        if entry["status"] in {"改义", "缺失", "证据无效"}:
            violations.append(f"{entry['id']}: {entry['status']}")
    return {"ok": not violations, "violations": violations, "advisories": advisories, "operator_issues": operator_issues, "bearing_total": total, "counts": dict(counts), "coverage_rate": rate, "entries": list(entries.values()), "reverse_entries": reverse_entries, "repair": repair, "extraction_issues": extraction_issues, "scope": "evidence existence and audit completeness only; meaning is reviewed by P8"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--article", required=True)
    parser.add_argument("--points-dir", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--k", type=int)
    parser.add_argument("--min-rate", type=float, default=0.95)
    parser.add_argument("--out-json")
    parser.add_argument("--operator-mode", choices=("off", "advisory", "strict"), default="advisory")
    arguments = parser.parse_args(argv)
    directory = Path(arguments.points_dir)
    files = [directory / f"{arguments.k}-points.md"] if arguments.k else sorted(directory.glob("*-points.md"))
    points = []
    parse_errors = []
    for path in files:
        parsed, errors = parse_points(path.read_text(encoding="utf-8"))
        points.extend(parsed)
        parse_errors.extend(errors)
    result = check_coverage(Path(arguments.article).read_text(encoding="utf-8"), points, Path(arguments.audit).read_text(encoding="utf-8"), arguments.min_rate, arguments.operator_mode)
    result["violations"].extend(parse_errors)
    result["ok"] = not result["violations"]
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

