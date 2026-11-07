import hashlib
import re
from collections import Counter

import textutil
from language import count_source_units, expected_zh_chars
from check_terms import faithful_paragraphs


LEAKS = (
    r"持有者[：:]", r"力度[：:]", r"译名把握度[：:]", r"清单未登记",
    r"加权覆盖率", r"承重项\s*\d", r"\[U?\d+\.\d+\]",
    r"对应原文[：:]\s*\[?P\d", r"无（原文未声明额外保留）",
)
RHETORIC = re.compile("精辟|敏锐|判了死刑|迎刃而解|理论大山|郑重澄明|科幻直觉的盲目轻信|壁垒已被破除|铺平了道路")
ARGUMENT_MODES = {"演绎", "归谬", "归纳", "溯因", "类比", "累积支持"}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def numbered_paragraphs(source):
    return {f"P{match[1]}": match[2].strip() for match in re.finditer(r"^\[P(\d+)\]\s*(.*?)(?=^\[P\d+\]|\Z)", source, re.M | re.S)}


def source_references(text):
    result = {f"P{number}" for number in re.findall(r"P(\d+)", text)}
    for first, last in re.findall(r"P(\d+)\]?\s*[–—-]\s*\[?P?(\d+)", text):
        result.update(f"P{number}" for number in range(int(first), int(last) + 1))
    return result


def english_words(text):
    return len(re.findall(r"\b[A-Za-z]+(?:[-’'][A-Za-z]+)*\b", text))


def reader_text_issues(text):
    return [f"reader-layer metadata: {match.group(0)}" for pattern in LEAKS for match in re.finditer(pattern, text)]


def term_variant_issues(text, plan):
    terms = (plan or {}).get("terms", [])
    canonical_spans = [(match.start(), match.end()) for term in terms if term.get("zh") for match in re.finditer(re.escape(term["zh"]), text)]
    issues = []
    for term in terms:
        for alias in term.get("alias_ban", []):
            if not alias or alias == term.get("zh"):
                continue
            for match in re.finditer(re.escape(alias), text):
                if not any(start <= match.start() and match.end() <= stop for start, stop in canonical_spans):
                    issues.append(f"term variant {alias!r}; canonical name is {term['zh']!r}")
                    break
    return issues


def check_source_audit(source, article, audit, points, coverage, source_lang='en'):
    violations = []
    paragraphs = numbered_paragraphs(source)
    point_map = {point["id"]: point for point in points}
    covered = {entry["id"] for entry in coverage.get("entries", []) if entry.get("status") == "完整" and entry.get("evidence") and textutil.compact(entry["evidence"]) in textutil.compact("\n\n".join(faithful_paragraphs(article)))}
    if {point['id'] for point in points if point['bearing'] == '是'} - covered:
        violations.append('bearing points have missing or incomplete current article evidence')
    if audit.get("source_sha256") != digest(source) or audit.get("article_sha256") != digest(article):
        violations.append("source audit is missing or stale; review the current source and article")
    records = audit.get("paragraphs", [])
    record_ids = [record.get("id") for record in records]
    if not paragraphs or set(record_ids) != set(paragraphs) or len(record_ids) != len(set(record_ids)):
        violations.append("source audit must account for each numbered paragraph exactly once, including exclusions")
    body = []
    for record in records:
        paragraph_id = record.get("id")
        if paragraph_id not in paragraphs:
            continue
        if record.get("scope") == "other":
            if not record.get("reason", "").strip():
                violations.append(f"{paragraph_id}: explain why this is outside the paper body")
            continue
        if record.get("scope") != "body":
            violations.append(f"{paragraph_id}: scope must be body or other")
            continue
        body.append(paragraphs[paragraph_id])
        status = record.get("status")
        if status == "covered":
            references = record.get("point_ids", [])
            if not references or not set(references) <= covered:
                violations.append(f"{paragraph_id}: coverage needs complete, current article evidence")
            for point_id in references:
                if paragraph_id not in source_references(point_map.get(point_id, {}).get("source_refs", "")):
                    violations.append(f"{paragraph_id}: point {point_id} does not cite this source paragraph")
        elif status in {"nonbearing", "excluded"}:
            if not record.get("reason", "").strip():
                violations.append(f"{paragraph_id}: give a specific reason for {status}")
            if status == "excluded" and record.get("bearing", True):
                violations.append(f"{paragraph_id}: a bearing omission cannot pass full-paper delivery")
        else:
            violations.append(f"{paragraph_id}: unreviewed or missing source content")
    if not body:
        violations.append("source audit identifies no body paragraphs")
    if "semantic_issues" not in audit:
        violations.append("source audit needs an explicit semantic_issues result from source-side review")
    violations.extend(str(issue) for issue in audit.get("semantic_issues", []))
    units = audit.get("units", [])
    unit_ids = [unit.get("id") for unit in units]
    if not units or any(not unit.get('id') or not unit.get('kind') for unit in units) or len(unit_ids) != len(set(unit_ids)):
        violations.append("source-side argument/example/objection/figure inventory is absent or duplicated")
    for unit in units:
        if unit.get("status") != "完整" or not unit.get("paragraph_ids") or not set(unit["paragraph_ids"]) <= set(paragraphs) or not unit.get("point_ids") or not set(unit["point_ids"]) <= covered:
            violations.append(f"source unit {unit.get('id')}: missing current, complete source-to-article mapping")
            continue
        referenced = {paragraph_id for point_id in unit['point_ids'] for paragraph_id in source_references(point_map.get(point_id, {}).get('source_refs', ''))}
        if set(unit['paragraph_ids']) - referenced:
            violations.append(f"source unit {unit.get('id')}: point evidence belongs to different source paragraphs")
    figure_numbers = set(re.findall(r"\b(?:Figure|Fig\.)\s*(\d+)", "\n".join(body), re.I))
    registered_figures = {str(unit.get("figure_number")) for unit in units if unit.get("kind") == "图示"}
    for number in sorted(figure_numbers - registered_figures):
        violations.append(f"source Figure {number}: no figure-reading unit in source inventory")
    if not coverage.get("ok") or coverage.get("extraction_issues") or any(entry.get("status") != "完整" for entry in coverage.get("repair", [])):
        violations.append("coverage has unresolved omissions, distortion, force changes or weak evidence")
    return {"ok": not violations, "violations": violations, "source_words": count_source_units("\n".join(body), source_lang), "source_units": len(units)}


def check_article(article, source_words, floor=0.75, term_plan=None, source_lang='en'):
    faithful = "\n\n".join(faithful_paragraphs(article))
    count = textutil.cjk_count(faithful)
    ratio = count / expected_zh_chars(source_words, source_lang) if source_words else None
    violations = reader_text_issues(article) + term_variant_issues(article, term_plan)
    advisories = [f"review rhetoric against source: {phrase}" for phrase in sorted(set(RHETORIC.findall(faithful)))]
    if not count:
        violations.append("faithful article body is empty")
    if ratio is None:
        violations.append("faithful-layer length requires the scoped source unit count")
    elif ratio < floor:
        advisories.append(f"review explanation against source: faithful-layer ratio {ratio:.3f} < {floor:.2f}; supplements and argument boxes do not count; completeness decides adequacy")
    sentences = Counter(textutil.compact(sentence) for sentence in textutil.split_sentences(faithful) if textutil.cjk_count(sentence) >= 12)
    advisories.extend(f"repeated full sentence ({frequency}): {sentence}" for sentence, frequency in sentences.items() if frequency > 1)
    if ratio is not None and not 0.9 <= ratio <= 1.3:
        advisories.append("outside initial 0.9–1.3 writing target; fix missing explanation, not word-count padding")
    if count and sum(textutil.cjk_count(match.group(0)) for match in re.finditer(r"所谓[^。！？]*?(?:指的是|是指)", faithful)) / count > 0.08:
        advisories.append("definition-template concentration: vary explanatory method according to concept type")
    return {"ok": not violations, "violations": violations, "advisories": advisories, "faithful_cjk": count, "source_words": source_words, "faithful_ratio": ratio, "scope": "Chinese faithful paragraphs / language-adjusted source units; approximate size, not semantic proof"}


def validate_teaching_units(units, points):
    point_map = {point["id"]: point for point in points}
    required = {point["id"] for point in points if point["bearing"] == "是"}
    represented = set()
    violations = []
    for index, unit in enumerate(units, 1):
        if any(not isinstance(unit.get(key), str) or not unit[key].strip() for key in ("question", "purpose", "method", "force_note")):
            violations.append(f"teaching unit {index}: question, purpose, method and force_note are required")
        tension = unit.get('dialectical_tension')
        if 'dialectical_tension' in unit and (not isinstance(tension, str) or not tension.strip()):
            violations.append(f"teaching unit {index}: dialectical_tension must be a non-empty string when provided")
        references = unit.get("point_ids", [])
        if not references or not set(references) <= point_map.keys():
            violations.append(f"teaching unit {index}: unknown or absent source points")
        represented.update(references)
        if not set(unit.get("example_point_ids", [])) <= set(references):
            violations.append(f"teaching unit {index}: examples need cited points in the same unit")
    if required - represented:
        violations.append("teaching units omit bearing points: " + ", ".join(sorted(required - represented)))
    return violations


def reader_sections(plan, merged, records, points, entries):
    if plan.get("article_sha256") != digest(merged):
        raise ValueError("reader plan is stale; review after the final article revision")
    point_map = {point["id"]: point for point in points}
    def check_text(item, label):
        if not item.get("text", "").strip() or not item.get("point_ids") or not set(item["point_ids"]) <= point_map.keys():
            raise ValueError(f"{label}: reader prose needs text and existing source ids")
        issues = reader_text_issues(item["text"])
        if issues:
            raise ValueError("; ".join(issues))
    check_text(plan.get("guide", {}).get("claim", {}), "guide claim")
    planned = {section["k"]: section for section in plan.get("sections", [])}
    if set(planned) != {record["k"] for record in records}:
        raise ValueError("reader plan sections differ from final article sections")
    for record in records:
        reader = planned[record["k"]]
        body = merged[record["start"]:record["end"]]
        paragraphs = textutil.split_paragraphs(body)
        boxes = []
        for box in reader.get("argument_boxes", []):
            if box.get("mode") not in ARGUMENT_MODES or not box.get("rule", "").strip():
                raise ValueError("argument box needs an actual inference mode and a reasoning rule; definitions are not arguments")
            roles = {item.get("role") for item in box.get("items", [])}
            if "结论" not in roles or not roles & {"前提", "隐含前提", "理由", "假设"}:
                raise ValueError("argument box needs reasons and a conclusion")
            for item in box["items"]:
                check_text(item, "argument step")
            evidence = entries.get(box.get("after_point"), {}).get("evidence", "")
            positions = [index for index, paragraph in enumerate(paragraphs, 1) if not paragraph.startswith("〔补充〕") and evidence and textutil.compact(evidence) in textutil.compact(paragraph)]
            if len(positions) != 1:
                raise ValueError("argument box needs a unique final-article insertion anchor")
            boxes.append({**box, "after_paragraph": positions[0]})
        if reader.get("summary"):
            check_text(reader["summary"], "section summary")
        record.update({"argument_boxes": boxes, "reader": reader})
    for item in plan.get("closing", {}).get("limits", []) + plan.get("closing", {}).get("argument_chain", []):
        check_text(item, "closing statement")
    for item in plan.get('closing', {}).get('limits', []):
        if not any(point_map[point_id].get('kind') == '自我限定' or point_map[point_id].get('force') == '作者保留' for point_id in item['point_ids']):
            raise ValueError('closing limit needs an explicit author reservation, not an inference from silence')
    return records

