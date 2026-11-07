import argparse
import json
import re
from pathlib import Path

from check_points import parse_points
from check_terms import faithful_paragraphs
import textutil


FORCES = {"断言", "倾向于", "试探", "仅表可能", "作者保留"}
STRONG_WORDS = ("彻底", "完全", "绝对", "绝非", "绝无", "毫无", "无可置疑", "百分之百", "极其", "严密", "完美", "击碎", "牢笼", "曙光", "幽灵", "免死金牌", "先验否决", "切实地", "过硬", "已证成")
HEDGES = {
    "倾向于": r"认为|倾向于|可以说|较为|有理由",
    "试探": r"可能|或许|似乎|大概|也许",
    "仅表可能": r"可能|能够|可以|原则上|在原则上",
    "作者保留": r"没有|并未|尚未|未曾|未论证|不声称|不主张|留给|不在.*范围",
}
EMPHASIS = re.compile(r"\b(?:thoroughly|completely|entirely|wholly|fully|absolutely|perfectly|certainly|undoubtedly)\b|无可置疑|完全|彻底", re.I)


def pure_navigation(sentence):
    # A narrow route instruction, with no inference, evaluation or author claim.
    # Anything with a second clause remains a substantive reverse-audit target.
    return bool(re.fullmatch(r'(?:下面|下文|接下来|下一节|下一部分|随后|最后|现在)(?:我们)?(?:将|会)?(?:介绍|讨论|考察|转向|来看|看|说明)'
                             r'[\u4e00-\u9fffA-Za-z0-9“”「」《》\s]{1,24}[。！？]?', sentence.strip())) and not \
        bool(re.search(r'因此|所以|说明了|证明|表明|可见|支持|成立|不成立|优于|不足|只有|必然|能够|可能|已经|我们得出|有意识|无意识|没有|不存在|意味着|导致|具备|具有|应当|必须|合理|错误|正确|是|为|不可靠|可靠|有效|无效|失败|困难|缺陷|优势|原因|理由|等于|属于|取决', sentence))


def reverse_covers(sentence, entry, normalized, known_ids):
    evidence = textutil.compact(entry.get('evidence', ''))
    ids = entry.get('point_ids', [])
    return bool(evidence) and evidence in normalized and textutil.compact(sentence) in evidence and \
        bool(ids) and set(ids) <= known_ids


def check_force(text, points=None, coverage=None, require_reverse=False):
    points = points or []
    coverage = coverage or {}
    point_map = {point["id"]: point for point in points}
    entries = coverage.get("entries", [])
    reverse = coverage.get("reverse_entries", [])
    paragraphs = faithful_paragraphs(text)
    sentences = [sentence for paragraph in paragraphs for sentence in textutil.split_sentences(paragraph)]
    violations = []
    advisories = []
    hits = []
    for sentence in sentences:
        words = [word for word in STRONG_WORDS for match in re.finditer(re.escape(word), sentence)]
        if not words:
            continue
        supporting = {entry["id"] for entry in entries if entry.get("status") == "完整" and entry.get("evidence") and textutil.compact(entry["evidence"]) in textutil.compact(sentence)}
        supporting.update(point_id for entry in reverse if reverse_covers(sentence, entry, textutil.compact(text), point_map.keys()) for point_id in entry.get("point_ids", []))
        authorized = any(EMPHASIS.search(point_map.get(point_id, {}).get('source_quote', '')) and (point_map.get(point_id, {}).get('force') == '断言' or re.search(HEDGES.get(point_map.get(point_id, {}).get('force'), r'(?!)'), sentence)) for point_id in supporting)
        hits.append({"sentence": sentence, "words": words, "point_ids": sorted(supporting), "authorized": authorized})
        if not authorized:
            advisories.append(f"review intensity against source: {','.join(words)} | {sentence}")
    total = sum(textutil.cjk_count(paragraph) for paragraph in paragraphs)
    rate = sum(len(hit["words"]) for hit in hits) * 1000 / total if total else 0
    if rate > 3:
        advisories.append("intensity frequency exceeds initial 3/1000-CJK guidance; source fidelity takes precedence")
    reviewed = 0
    retained = 0
    normalized = textutil.compact("\n\n".join(paragraphs))
    cue_evidence = {}
    for entry in entries:
        evidence = entry.get("evidence", "")
        if entry.get("status") in {"完整", "弱化"} and textutil.compact(evidence) and textutil.compact(evidence) in normalized:
            cue_evidence.setdefault(entry["id"], []).append(evidence)
    for entry in reverse:
        evidence = entry.get("evidence", "")
        if textutil.compact(evidence) and textutil.compact(evidence) in normalized:
            for point_id in entry.get("point_ids", []):
                cue_evidence.setdefault(point_id, []).append(evidence)
    for point in points:
        force = point.get("force")
        if force and force not in FORCES:
            violations.append(f"{point['id']}: invalid force")
        if force not in HEDGES or point["id"] not in cue_evidence:
            continue
        reviewed += 1
        evidence = " ".join(cue_evidence[point["id"]])
        if re.search(HEDGES[force], evidence):
            retained += 1
        else:
            advisories.append(f"{point['id']}: no force-specific hedge cue; P8 must review the full proposition")
    for entry in entries:
        if re.search(r"(?<!无)(?<!未)(?<!无任何)(?<!未发生)(?<!没有)(?<!不存在)力度(?:升级|降级)", entry.get("explanation", "")):
            violations.append(f"{entry['id']}: semantic force mismatch recorded by P8")
    for entry in reverse:
        if not entry.get("point_ids") and not (entry.get('kind') in {'过渡', '导航'} and pure_navigation(entry.get('evidence', ''))):
            violations.append(f"unsupported sentence: {entry.get('evidence', '')}")
        if any(point_id not in point_map for point_id in entry.get("point_ids", [])):
            violations.append("reverse audit cites unknown point ids")
        if not entry.get("evidence") or textutil.compact(entry["evidence"]) not in textutil.compact(text):
            violations.append("reverse audit evidence absent from text")
    if require_reverse:
        endings = [sentence for paragraph in paragraphs[-1:] for sentence in textutil.split_sentences(paragraph)]
        for sentence in set(endings):
            if pure_navigation(sentence):
                continue
            if not any(reverse_covers(sentence, entry, normalized, point_map.keys()) for entry in reverse):
                violations.append(f"ending sentence lacks full reverse evidence: {sentence}")
        if not points and any(not pure_navigation(sentence) for sentence in endings):
            violations.append("force provenance requires points; missing points cannot certify fidelity")
    return {"ok": not violations, "violations": violations, "advisories": advisories, "metrics": {"cjk_count": total, "intensity_per_1000": rate, "non_assertion_items": reviewed, "hedge_cue_retention": retained / reviewed if reviewed else None}, "hits": hits, "heuristic": True, "scope": "lexical intensity and audit provenance, not semantic proof of modal scope"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--points-dir")
    parser.add_argument("--coverage-json")
    parser.add_argument("--require-reverse", action="store_true")
    parser.add_argument("--out-json")
    arguments = parser.parse_args(argv)
    points = []
    errors = []
    if arguments.points_dir:
        for path in sorted(Path(arguments.points_dir).glob("*-points.md"), key=lambda p: int(re.search(r'\d+', p.name).group()) if re.search(r'\d+', p.name) else 0):
            parsed, violations = parse_points(path.read_text(encoding="utf-8"))
            points.extend(parsed)
            errors.extend(violations)
    coverage = json.loads(Path(arguments.coverage_json).read_text(encoding="utf-8")) if arguments.coverage_json else {}
    result = check_force(Path(arguments.text).read_text(encoding="utf-8"), points, coverage, arguments.require_reverse)
    result["violations"].extend(errors)
    result["ok"] = not result["violations"]
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(json.dumps(textutil.report_summary(result, arguments.out_json), ensure_ascii=False) if arguments.out_json else output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

