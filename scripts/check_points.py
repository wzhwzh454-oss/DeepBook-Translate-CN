import argparse
import json
import re
from pathlib import Path

import textutil
from language import count_source_units
from workspace_config import source_language
from bt_common import quote_long_enough
from quote_match import match_quote, quote_diagnostic


KINDS = {"问题", "定义", "区分", "主张", "前提", "推理", "结论", "限定", "案例", "案例作用", "异议", "回应", "让步", "背景", "方法", "论证策略", "自我限定", "叙事", "场景", "对话", "史实", "现象", "心理", "意象"}
FIELDS = ("id", "kind", "holder", "statement", "qualifiers", "source_refs", "bearing", "source_quote", "hint")
V2_FIELDS = FIELDS + ("force", "argument", "terms")
FORCES = {"断言", "倾向于", "试探", "仅表可能", "作者保留"}
ARG_ROLES = {"前提", "中间结论", "结论", "假设", "限定"}
ARG_MODES = {"演绎", "归谬", "类比", "最佳解释", "诉诸例证"}


def parse_points(text):
    points = []
    violations = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [cell.strip() for cell in line.split("｜")]
        if len(cells) not in {len(FIELDS), len(V2_FIELDS)}:
            violations.append(f"line {number}: expected 9 or 12 fields")
            continue
        fields = V2_FIELDS if len(cells) == len(V2_FIELDS) else FIELDS
        points.append({**dict(zip(fields, cells)), "line": number})
    return points, violations


def source_paragraphs(text):
    return {int(match[1]): match[2].strip() for match in re.finditer(r"^\[P(\d+)\]\s*(.*?)(?=^\[P\d+\]|\Z)", text, re.M | re.S)}


def check_points(text, numbered, section, term_plan=None, schema_version=1, source_map=None, source_lang='en'):
    points, violations = parse_points(text)
    advisories = []
    quote_matches, quote_diagnostics = [], []
    mappings = {record['paragraph_id']: record for record in (source_map or {}).get('paragraphs_map', [])}
    paragraphs = source_paragraphs(numbered)
    allowed = {number for start, stop in section["anchors"] for number in range(start, stop + 1)}
    if not points:
        violations.append("no points")
    units = {}
    term_ids = {term["id"] for term in (term_plan or {}).get("terms", [])}
    for index, point in enumerate(points, 1):
        prefix = f"line {point['line']} ({point['id']})"
        if point["id"] != f"{section['k']}.{index}":
            violations.append(f"{prefix}: non-contiguous id")
        if point["kind"] not in KINDS:
            violations.append(f"{prefix}: unknown kind")
        if not point["holder"]:
            violations.append(f"{prefix}: missing holder")
        if not point["statement"]:
            violations.append(f"{prefix}: statement empty")
        elif textutil.cjk_count(point["statement"]) > 70:
            advisories.append(f"{prefix}: statement over 70 CJK; review proposition boundaries without dropping qualifiers")
        if not point["qualifiers"] or not point["hint"]:
            violations.append(f"{prefix}: use 无 for absent qualifiers/hint")
        if point["bearing"] not in {"是", "否"}:
            violations.append(f"{prefix}: bearing must be 是/否")
        if "force" in point or schema_version == 2:
            if point.get("force") not in FORCES:
                violations.append(f"{prefix}: missing/invalid force")
            if point["kind"] in {"论证策略", "自我限定"} and point["bearing"] != "是":
                violations.append(f"{prefix}: strategy/reservation must be bearing")
            argument = point.get("argument", "").replace("：", ":")
            if argument != "无":
                parts = argument.split(":")
                if len(parts) != 3 or not re.fullmatch(r"U[\d.]+", parts[0]) or parts[1] not in ARG_ROLES or parts[2] not in ARG_MODES:
                    violations.append(f"{prefix}: invalid argument; use U1.1:前提:归谬 or 无")
                else:
                    units.setdefault(parts[0], []).append((parts[1], parts[2]))
                    if point["bearing"] != "是":
                        violations.append(f"{prefix}: argument steps cannot be non-bearing")
            terms = point.get("terms", "").replace("；", ";").replace("：", ":")
            if terms != "无":
                for reference in terms.split(";"):
                    parts = reference.strip().split(":")
                    if len(parts) != 2 or parts[1] not in {"新", "回指"} or not re.fullmatch(r"T[\w.-]+", parts[0]):
                        violations.append(f"{prefix}: invalid term state")
                    elif term_plan is not None and parts[0] not in term_ids:
                        violations.append(f"{prefix}: unknown term {parts[0]}")
        refs = [int(value) for value in re.findall(r"\[P(\d+)\]", point["source_refs"])]
        if not refs or any(value not in allowed or value not in paragraphs for value in refs):
            violations.append(f"{prefix}: source outside section anchors")
        if not quote_long_enough(point['source_quote']):
            violations.append(f"{prefix}: source quote too short to evidence a proposition (need >=12 letters/CJK chars)")
        matched = [(value, match_quote(point['source_quote'], paragraphs.get(value, ''), mappings.get(f'P{value}'))) for value in refs]
        matches = [(value, result) for value, result in matched if result is not None]
        if not matches:
            diagnostic = {'point_id': point['id'], **quote_diagnostic(point['source_quote'], {f'P{value}': paragraphs[value] for value in refs if value in paragraphs})}
            quote_diagnostics.append(diagnostic)
            violations.append(f"{prefix}: source quote absent from cited paragraph; nearest {diagnostic.get('paragraph_id', '?')}: {diagnostic['source_fragment'][:140]}")
        else:
            value, result = min(matches, key=lambda item: item[1]['mode'] != 'literal')
            quote_matches.append({'point_id': point['id'], 'paragraph_id': f'P{value}', **result})
            if result['mode'] != 'literal':
                advisories.append(f"{prefix}: quote matched P{value} only as {result['mode']} (punctuation/dash/quote/wrap differences); raw: {result['raw_fragment'][:140]}")
        if len(re.findall(r"\b[\w'-]+\b", point["source_quote"])) > 12:
            advisories.append(f"{prefix}: source quote over 12 words; review length while retaining necessary continuous source evidence")
    for unit, roles in units.items():
        if not any(role == "结论" for role, mode in roles):
            violations.append(f"{unit}: argument unit lacks a conclusion")
        if len({mode for role, mode in roles}) != 1:
            violations.append(f"{unit}: inconsistent inference mode")
    for number in sorted(allowed):
        if re.search(r"I (?:am not|do not take|stopped short|am yet to)|beyond (?:my|the) scope", paragraphs.get(number, ""), re.I):
            if not any(point["kind"] in {"论证策略", "自我限定"} and f"[P{number}]" in point["source_refs"] for point in points):
                advisories.append(f"[P{number}]: possible missing strategy/reservation; inspect source")
    bearing = sum(point["bearing"] == "是" for point in points)
    if points and bearing / len(points) < 0.6:
        advisories.append("more than 40% of points are non-bearing; inspect extraction")
    words = sum(count_source_units(paragraphs.get(number, ""), source_lang) for number in allowed)
    if source_lang == 'en' and words and not 3 <= bearing * 100 / words <= 6:
        advisories.append("bearing density outside initial 3–6 per 100 English words; not a semantic verdict")
    return {"ok": not violations, "violations": violations, "advisories": advisories, "points": points, "bearing_total": bearing,
            "quote_matches": quote_matches, "quote_diagnostics": quote_diagnostics}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", required=True)
    parser.add_argument("--numbered", required=True)
    parser.add_argument("--outline-json", required=True)
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--out-json")
    parser.add_argument("--term-plan")
    parser.add_argument('--source-map', help='defaults to input/pdf-extraction.json beside numbered source')
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=1)
    arguments = parser.parse_args(argv)
    outline = json.loads(Path(arguments.outline_json).read_text(encoding="utf-8"))
    section = next(section for section in outline["sections"] if section["k"] == arguments.k)
    term_plan = json.loads(Path(arguments.term_plan).read_text(encoding="utf-8")) if arguments.term_plan else None
    map_path = Path(arguments.source_map) if arguments.source_map else Path(arguments.numbered).parent / 'input/pdf-extraction.json'
    source_map = json.loads(map_path.read_text(encoding='utf-8')) if map_path.is_file() else None
    result = check_points(Path(arguments.points).read_text(encoding="utf-8"), Path(arguments.numbered).read_text(encoding="utf-8"), section, term_plan, arguments.schema_version, source_map, source_lang=source_language(arguments.numbered))
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(json.dumps({'ok': result['ok'], 'violations': len(result['violations']), 'samples': result['violations'][:4],
                      'advisory_count': len(result['advisories']), 'advisories': result['advisories'][:3],
                      'quote_diagnostics': result['quote_diagnostics'][:3], 'report': arguments.out_json}, ensure_ascii=False) if arguments.out_json else output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

