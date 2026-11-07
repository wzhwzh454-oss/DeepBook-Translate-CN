import argparse
import csv
import json
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from bt_common import norm_orig
import re
from collections import Counter
from pathlib import Path

import textutil


REQUIRED = {"id", "zh", "orig", "level", "gloss", "role", "example_src", "depends_on", "first_section", "confusable_with", "alias_ban"}


def check_term_plan(plan, outline, numbered=None, glossary=None, strict_load=False, locked_terms=None):
    violations = []
    advisories = []
    terms = plan.get("terms", []) if isinstance(plan, dict) else []
    sections = {section["k"] for section in outline.get("sections", [])}
    valid = []
    for owner in [plan, *terms] if isinstance(terms, list) else [plan]:
        if isinstance(owner, dict) and 'user_banned' in owner and (not isinstance(owner['user_banned'], list) or
                any(not isinstance(value, str) or not value.strip() for value in owner['user_banned'])):
            violations.append('user_banned must be a string array copied from explicit user prohibitions')
    if not isinstance(terms, list):
        return {"ok": False, "violations": ["terms must be an array"], "advisories": [], "topological_order": []}
    for index, term in enumerate(terms, 1):
        if not isinstance(term, dict) or REQUIRED - term.keys():
            violations.append(f"term {index}: missing required fields")
            continue
        if any(not isinstance(term[field], str) or not term[field].strip() for field in ("id", "zh", "orig", "level", "gloss", "role")):
            violations.append(f"term {index}: names/gloss/role must be non-empty strings")
            continue
        if not re.fullmatch(r"T[\w.-]+", term["id"]):
            violations.append(f"{term['id']}: invalid term id")
        if term["level"] not in {"核心", "辅助"}:
            violations.append(f"{term['id']}: invalid level")
        if term.get('inherited') is True:
            pass  # locked term inherited from an earlier chapter: no first_section in this chapter
        elif type(term["first_section"]) is not int or term["first_section"] not in sections:
            violations.append(f"{term['id']}: first_section is not an outline section")
        if textutil.cjk_count(term["gloss"]) > 25 or textutil.cjk_count(term["role"]) > 30:
            advisories.append(f"{term['id']}: gloss/role exceeds initial length guidance")
        if any(not isinstance(term[field], list) or any(not isinstance(value, str) or not value for value in term[field]) for field in ("depends_on", "confusable_with", "alias_ban")):
            violations.append(f"{term['id']}: dependencies/confusables/aliases must be string arrays")
            continue
        if term["zh"] in term["alias_ban"]:
            violations.append(f"{term['id']}: canonical name is banned")
        example = term["example_src"]
        if example is not None and (not isinstance(example, str) or not re.fullmatch(r"\[P\d+\]", example)):
            violations.append(f"{term['id']}: example_src must be [Pn] or null")
        elif example and numbered is not None and not re.search(rf"^{re.escape(example)}\s", numbered, re.M):
            violations.append(f"{term['id']}: example source absent")
        if example is None:
            advisories.append(f"{term['id']}: no source example; require a source-backed reference, not an invented faithful-layer example")
        valid.append(term)
    for field in ("id", "zh", "orig"):
        values = [term[field].strip().casefold() for term in valid]
        for value, count in Counter(values).items():
            if count > 1:
                violations.append(f"duplicate {field}: {value}; disambiguate senses explicitly")
    term_map = {term["id"]: term for term in valid}
    ledger_uids = {t.get('uid') for t in (locked_terms or []) if t.get('uid')}
    ledger_zh = {t.get('zh') for t in (locked_terms or []) if t.get('zh')}

    def external(reference):
        # c01:T3 (global uid) or ledger:<中文译名> point at a LOCKED term of an earlier chapter
        return reference in ledger_uids or (reference.startswith('ledger:') and reference[7:] in ledger_zh)

    graph = {}
    for term in valid:
        dependencies = set(term["depends_on"])
        graph[term["id"]] = dependencies
        for dependency in dependencies | set(term["confusable_with"]):
            if dependency not in term_map and not external(dependency):
                violations.append(f"{term['id']}: unknown related term {dependency}")
        for dependency in dependencies & term_map.keys():
            if isinstance(term_map[dependency]["first_section"], int) and isinstance(term["first_section"], int) and term_map[dependency]["first_section"] > term["first_section"]:
                violations.append(f"{term['id']}: dependency is introduced later")
    order = []
    pending = {key: value & graph.keys() for key, value in graph.items()}
    while pending:
        ready = sorted(key for key, dependencies in pending.items() if not dependencies)
        if not ready:
            violations.append("cyclic term dependencies")
            break
        order.extend(ready)
        pending = {key: dependencies - set(ready) for key, dependencies in pending.items() if key not in ready}
    counts = Counter(term["first_section"] for term in valid if term["level"] == "核心" and type(term["first_section"]) is int)
    for section, count in counts.items():
        if count > 4:
            (violations if strict_load else advisories).append(f"section {section}: {count} new core terms > initial target 4")
    if glossary:
        with Path(glossary).open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("locked", "true").strip().casefold() in {"true", "1"}:
                    original = row.get("orig", "").strip().casefold()
                    matching = next((term for term in valid if term["orig"].strip().casefold() == original), None)
                    if not matching or matching["zh"] != row.get("zh", "").strip():
                        violations.append(f"locked glossary changed or omitted: {original}")
    for locked in locked_terms or []:
        if locked.get('locked'):
            original = norm_orig(locked.get('orig'), locked.get('source_lang', 'en'))  # hyphen / plural / case tolerant
            matching = next((term for term in valid if norm_orig(term['orig'], term.get('source_lang', 'en')) == original), None)
            if matching and matching['zh'] != locked.get('zh'):
                violations.append(f'locked ledger drift: {original}')
    return {"ok": not violations, "violations": violations, "advisories": advisories, "topological_order": order, "new_core_by_section": dict(counts), "scope": "schema, source-reference existence and dependency consistency; gloss semantics need source review"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--term-plan", required=True)
    parser.add_argument("--outline-json", required=True)
    parser.add_argument("--numbered")
    parser.add_argument("--glossary")
    parser.add_argument("--strict-load", action="store_true")
    parser.add_argument("--out-json")
    parser.add_argument('--state', help='legacy: JSON object with a term_ledger list')
    parser.add_argument('--global-terms', help='global-term-ledger.json (list or {terms: [...]}): enables locked-translation drift and cross-chapter dependency checks')
    arguments = parser.parse_args(argv)
    locked_terms = json.loads(Path(arguments.state).read_text(encoding='utf-8')).get('term_ledger', []) if arguments.state else None
    if arguments.global_terms and Path(arguments.global_terms).exists():
        ledger = json.loads(Path(arguments.global_terms).read_text(encoding='utf-8-sig'))
        locked_terms = (locked_terms or []) + (ledger.get('terms', []) if isinstance(ledger, dict) else ledger)
    result = check_term_plan(json.loads(Path(arguments.term_plan).read_text(encoding="utf-8")), json.loads(Path(arguments.outline_json).read_text(encoding="utf-8")), Path(arguments.numbered).read_text(encoding="utf-8") if arguments.numbered else None, arguments.glossary, arguments.strict_load, locked_terms)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(json.dumps(textutil.report_summary(result, arguments.out_json), ensure_ascii=False) if arguments.out_json else output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

