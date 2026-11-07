import argparse
import json
import re
from pathlib import Path

from check_term_plan import check_term_plan
import textutil
from check_draft import USER_FORBIDDEN


def faithful_paragraphs(text):
    return [textutil.reader_plain_text(paragraph) for paragraph in textutil.split_paragraphs(text) if not paragraph.lstrip().startswith(("〔补充〕", "#", "<!--"))]


def term_variant_report(text, plan=None):
    """One lexical policy for chapters, reader fields and book text.

    Model-proposed aliases need source/context review. A locked canonical name
    does not make every substring a user prohibition. user_banned only carries
    expressions explicitly prohibited by the user; it is optional, not an
    approval/exception register.
    """
    terms = (plan or {}).get("terms", [])
    canonical = [(m.start(), m.end()) for term in terms if term.get("zh")
                 for m in re.finditer(re.escape(term["zh"]), text)]
    violations, advisories, matches = [], [], []
    forbidden = set(USER_FORBIDDEN) | set((plan or {}).get("user_banned", []))
    forbidden.update(value for term in terms for value in term.get("user_banned", []))
    candidates = [(alias, term) for term in terms for alias in term.get("alias_ban", [])
                  if alias and alias != term.get("zh") and alias not in forbidden]
    for alias, term in [(value, None) for value in sorted(forbidden)] + candidates:
        for match in re.finditer(re.escape(alias), text):
            hard = term is None
            if not hard and any(start <= match.start() and match.end() <= stop for start, stop in canonical):
                continue
            line = text.count("\n", 0, match.start()) + 1
            column = match.start() - text.rfind("\n", 0, match.start())
            context = text[max(0, match.start()-36):min(len(text), match.end()+36)].replace("\n", " ")
            detail = (f"user-banned expression {alias!r}" if hard else
                      f"review term candidate {alias!r}; canonical name is {term['zh']!r}")
            detail += f" at line {line}:{column}: {context}"
            (violations if hard else advisories).append(detail)
            matches.append({"alias": alias, "term_id": term.get("id") if term else None,
                            "start": match.start(), "end": match.end(), "line": line,
                            "column": column, "context": context, "hard": hard})
    return {"violations": violations, "advisories": advisories, "matches": matches}


def check_terms(sections, plan, strict_load=False, advisory_sections=None):
    violations = []
    advisories = []
    first = {}
    terms = plan["terms"]
    term_map = {term["id"]: term for term in terms}
    for term in terms:
        if term.get('inherited') is True:  # introduced in an earlier chapter: no first-use obligations
            first[term['id']] = {'section': 0, 'paragraph': 0, 'offset': 0}
    targets = None if advisory_sections is None else set(advisory_sections)

    def advise(issue, section):
        if targets is None or section in targets:
            advisories.append(issue)

    for section in sections:
        paragraphs = faithful_paragraphs(section["text"])
        text = "\n\n".join(paragraphs)
        new_core = []
        offset = 0
        for paragraph_index, paragraph in enumerate(paragraphs, 1):
            occurrences = []
            checked = term_variant_report(paragraph, plan)
            label = f"section {section['k']} paragraph {paragraph_index}: "
            violations.extend(label + issue for issue in checked['violations'])
            for issue in checked['advisories']:
                advise(label + issue, section['k'])
            for term in terms:
                for match in re.finditer(re.escape(term["zh"]), paragraph):
                    occurrences.append((match.start(), match.end(), term))
            occurrences.sort(key=lambda item: (item[0], -(item[1] - item[0])))
            covered_until = -1
            new_in_paragraph = []
            for start, stop, term in occurrences:
                if start < covered_until:
                    continue
                covered_until = stop
                if term["id"] in first:
                    continue
                first[term["id"]] = {"section": section["k"], "paragraph": paragraph_index, "offset": offset + start}
                if isinstance(term.get('first_section'), int) and section["k"] < term["first_section"]:
                    if textutil.cjk_count(term['zh']) >= 3:
                        violations.append(f"{term['id']}: used before planned section")
                    else:  # 1-2 character terms (知识/信念) occur incidentally in ordinary prose
                        advise(f"{term['id']}: short term appears before its planned section (likely incidental)", section['k'])
                elif isinstance(term.get('first_section'), int) and section["k"] != term["first_section"]:
                    advise(f"{term['id']}: introduced later than planned; update the plan", section["k"])
                for dependency in term["depends_on"]:
                    if dependency in term_map and dependency not in first:  # c01:T3 / ledger:<zh> are earlier-chapter terms
                        violations.append(f"{term['id']}: used before dependency {dependency}")
                tail = paragraph[start:]
                if textutil.compact(term["gloss"]) not in textutil.compact(paragraph) and not re.search(r"就是|指(?:的是)?|意思是|也就是|叫作|说的是", tail):
                    advise(f"{term['id']}: no first-paragraph explanation cue; explanation requires semantic review", section["k"])
                if textutil.compact(term["role"]) not in textutil.compact(paragraph):
                    advise(f"{term['id']}: first-use role requires semantic review", section["k"])
                if not re.search(r"比如|例如|例子|前文|上文|刚才|回看", paragraph):
                    advise(f"{term['id']}: first-use example/reference requires semantic review", section["k"])
                if term["level"] == "核心":
                    new_core.append(term["id"])
                    new_in_paragraph.append(term["id"])
                    remaining = text[offset + stop:]
                    recurrence = remaining.find(term["zh"])
                    if recurrence < 0 or textutil.cjk_count(remaining[:recurrence]) > 300:
                        advise(f"{term['id']}: no explicit name recurrence within initial 300-CJK guidance; pronoun references need review", section["k"])
            if len(new_in_paragraph) > 1:
                issue = f"section {section['k']} paragraph {paragraph_index}: {len(new_in_paragraph)} new core terms"
                if strict_load:
                    violations.append(issue)
                else:
                    advise(issue, section["k"])
            offset += len(paragraph) + 2
        count = textutil.cjk_count(text)
        if len(new_core) > 4 or count and len(new_core) * 1000 / count > 6:
            issue = f"section {section['k']}: core-term load exceeds initial 4/section or 6/1000-CJK guidance"
            if strict_load:
                violations.append(issue)
            else:
                advise(issue, section["k"])
    for term_id, term in term_map.items():
        if term["level"] == "核心" and not term.get('inherited') and term_id not in first and any(section["k"] == term["first_section"] for section in sections):
            violations.append(f"{term_id}: planned core term absent")
    return {"ok": not violations, "violations": violations, "advisories": advisories, "first_occurrences": first, "heuristic": True, "scope": "lexical checks cannot certify explanation, role, examples or synonym equivalence"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--term-plan", required=True)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--marked", action="store_true")
    parser.add_argument("--strict-load", action="store_true")
    parser.add_argument("--advisory-k", type=int, action="append", help="Limit advisories to these sections while retaining all context and hard checks")
    parser.add_argument('--sections-dir')
    parser.add_argument("--out-json")
    parser.add_argument("--global-terms", help="global-term-ledger.json: lets depends_on reference earlier-chapter locked terms")
    arguments = parser.parse_args(argv)
    text = Path(arguments.text).read_text(encoding="utf-8")
    if arguments.marked:
        from apply_patches import split_marked
        sections = [{"k": number, "text": body} for number, body in split_marked(text)]
    else:
        sections = [{"k": arguments.k, "text": text}]
        if arguments.sections_dir:
            prior = [{"k": number, "text": (Path(arguments.sections_dir) / f'{number}-final.md').read_text(encoding='utf-8')} for number in range(1, arguments.k)]
            sections = prior + sections
    plan = json.loads(Path(arguments.term_plan).read_text(encoding="utf-8"))
    locked = None
    if getattr(arguments, 'global_terms', None) and Path(arguments.global_terms).exists():
        ledger = json.loads(Path(arguments.global_terms).read_text(encoding='utf-8-sig'))
        locked = ledger.get('terms', []) if isinstance(ledger, dict) else ledger
    validation = check_term_plan(plan, {"sections": [{"k": term.get("first_section")} for term in plan.get("terms", []) if isinstance(term, dict) and type(term.get('first_section')) is int]}, locked_terms=locked)
    targets = arguments.advisory_k if arguments.advisory_k is not None else (None if arguments.marked else [arguments.k])
    result = check_terms(sections, plan, arguments.strict_load, advisory_sections=targets) if validation["ok"] else validation
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(json.dumps(textutil.report_summary(result, arguments.out_json), ensure_ascii=False) if arguments.out_json else output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

