# -*- coding: utf-8 -*-
"""check_outline.py — validate outline.md against the P1 contract.

Checks: per-section field completeness; anchor ranges legal and non-empty
(against the numbered source); budgets numeric (and, when config.total_words
is given, budget sum within [1.0, 1.2] x total_words); no more than one section
carries the strongest objection; self-check table all "通过".
On success writes outline.json (structured outline incl. term table draft).

Usage:
  python3 check_outline.py --outline workspace/outline.md \
      --numbered workspace/source-numbered.md \
      [--config workspace/input/config.json] --out-json workspace/outline.json

Output (stdout JSON): {"ok": bool, "violations": [...], "outline_json": path}
"""
import argparse
import io
import json
import re
import sys

from language import count_source_units
from workspace_config import source_language

SECTION_FIELDS = [
    ('position', '\u4f4d\u7f6e'),                 # 位置
    ('sub_question', '\u672c\u8282\u5b50\u95ee\u9898'),       # 本节子问题
    ('inherits', '\u627f\u63a5\u7684\u9057\u7559\u95ee\u9898'),     # 承接的遗留问题
    ('core_content', '\u6838\u5fc3\u5185\u5bb9'),           # 核心内容
    ('conclusion', '\u672c\u8282\u7ed3\u8bba'),           # 本节结论
    ('chain_role', '\u627f\u62c5\u94fe\u6bb5'),           # 承担链段
    ('anchors_raw', '\u6e90\u6587\u951a\u70b9'),           # 源文锚点
    ('prohibited_raw', '\u7981\u5199\u6e05\u5355'),         # 禁写清单
    ('open_question', '\u9057\u7559\u95ee\u9898'),          # 遗留问题
    ('budget_raw', '\u5b57\u6570\u9884\u7b97'),           # 字数预算
]

ANCHOR_RE = re.compile(r'P(\d+)(?:\s*[\-\u2013\u2014]\s*P?(\d+))?')
OPTIONAL_FIELDS = [('stage_label', '阶段全称'), ('stage_short', '阶段简称')]
OBJECTION_MARK = '\u542b\u6700\u5f3a\u5f02\u8bae'  # 含最强异议


def parse_outline(text):
    header = {}
    excluded = []
    sections = []
    terms = []
    selfcheck = []
    mode = None
    cur = None
    lines = text.splitlines()
    n = len(lines)

    def collect_indented(start):
        """Collect stripped indented lines from `start`; stop at the first
        line with no leading whitespace (a top-level field/heading/blank).
        Returns (parts, next_index)."""
        parts = []
        j = start
        while j < n:
            nxt = lines[j]
            ns = nxt.strip()
            if not ns:
                j += 1
                continue
            if nxt == nxt.lstrip():  # unindented top-level line ends the block
                break
            parts.append(ns)
            j += 1
        return parts, j

    i = 0
    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith('# \u5927\u7eb2\u5934\u90e8'):  # # 大纲头部
            mode = 'header'
            i += 1
            continue
        if s.startswith('# \u672f\u8bed\u8868\u521d\u7a3f'):  # # 术语表初稿
            mode = 'terms'
            i += 1
            continue
        if s.startswith('# \u81ea\u67e5\u8868'):  # # 自查表
            mode = 'check'
            i += 1
            continue
        m = re.match(r'^###\s*\u7b2c\s*(\d+)\s*\u8282[\uff1a:]\s*(.+)$', s)
        if m:  # ### 第 k 节：title
            cur = {'k': int(m.group(1)), 'title': m.group(2).strip(), 'fields': {}}
            sections.append(cur)
            mode = 'section'
            i += 1
            continue
        if mode == 'header' and s.startswith('- '):
            body = s[2:]
            if body.startswith('\u5168\u6587\u6838\u5fc3\u95ee\u9898'):  # 全文核心问题
                header['thesis'] = body.split('\uff1a', 1)[-1].strip()
            elif body.startswith('\u603b\u8282\u6570'):  # 总节数
                header['total_sections_raw'] = body
                m2 = re.search(r'\u603b\u8282\u6570[\uff1a:]\s*(\d+)', body)
                header['total_sections'] = int(m2.group(1)) if m2 else None
                m3 = re.search(r'\u603b\u5b57\u6570\u9884\u7b97[\uff1a:]\s*(\d+)', body)
                header['total_budget'] = int(m3.group(1)) if m3 else None
            elif body.startswith('\u672a\u7eb3\u5165\u5185\u5bb9'):  # 未纳入内容
                rest = body.split('\uff1a', 1)[-1].strip()
                if rest and rest != '\u65e0':
                    excluded.append(rest)
                # multi-line list: collect indented continuation lines
                parts, j = collect_indented(i + 1)
                for p in parts:
                    excluded.append(p.lstrip('- ').strip())
                i = j
                continue
            i += 1
            continue
        if mode == 'header' and s.startswith('\u672a\u7eb3\u5165'):
            excluded.append(s)
            i += 1
            continue
        if mode == 'header' and s.startswith('-') and not s.startswith('- '):
            excluded.append(s.lstrip('-').strip())
            i += 1
            continue
        if mode == 'terms':
            cells = [c.strip() for c in s.split('\uff5c') if c.strip()]  # ｜
            if len(cells) >= 2 and not s.startswith('\u4e2d\u6587\u8bd1\u540d'):
                term = {'zh': cells[0],
                              'orig': cells[1],
                              'defined_in': int(cells[2]) if len(cells) > 2 and cells[2].isdigit() else None}
                if len(cells) > 3:
                    term['gloss'] = cells[3]
                if len(cells) > 4:
                    term['confidence'] = cells[4]
                terms.append(term)
            i += 1
            continue
        if mode == 'check':
            selfcheck.append(s)
            i += 1
            continue
        if mode == 'section' and cur is not None and s.startswith('- '):
            body = s[2:]
            matched = False
            advanced = False
            for key, label in SECTION_FIELDS + OPTIONAL_FIELDS:
                if body.startswith(label):
                    if '\uff1a' in body or ':' in body:
                        val = re.split('[\uff1a:]', body, 1)[-1].strip()
                    else:
                        # 无冒号的字段行不是合法字段值，按缺失处理（下游报违规）。
                        val = ''
                    # 核心内容/禁写清单 may span multiple indented lines;
                    # continuation lines get their '- ' prefix stripped and
                    # are joined even when the first line already has a value.
                    if key in ('core_content', 'prohibited_raw'):
                        parts, j = collect_indented(i + 1)
                        cont = [p.lstrip('- ').strip() for p in parts]
                        cont = [p for p in cont if p]
                        if cont:
                            joined = '\uff1b'.join(cont)
                            val = (val + '\uff1b' + joined) if val else joined
                        i = j
                        advanced = True
                    cur['fields'][key] = val
                    matched = True
                    break
            if not matched:
                cur['fields'].setdefault('_extra', []).append(body)
            if not advanced:
                i += 1
            continue
        i += 1
    return header, excluded, sections, terms, selfcheck


def parse_anchors(raw):
    out = []
    for m in ANCHOR_RE.finditer(raw or ''):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        out.append([min(a, b), max(a, b)])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--outline', required=True)
    ap.add_argument('--numbered', required=True)
    ap.add_argument('--config', default=None)
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--advisory-budget', action='store_true')
    ap.add_argument('--require-stages', action='store_true')
    args = ap.parse_args(argv)

    violations = []
    advisories = []
    try:
        with io.open(args.outline, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read outline: %s' % e]},
                         ensure_ascii=False))
        return 1
    try:
        with io.open(args.numbered, encoding='utf-8') as f:
            numbered = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read numbered source: %s' % e]},
                         ensure_ascii=False))
        return 1

    n_paras = len(re.findall(r'^\[P\d+\]', numbered, flags=re.M))
    if n_paras == 0:
        violations.append('numbered source has no [Pk] paragraphs')

    config = {}
    if args.config:
        try:
            with io.open(args.config, encoding='utf-8') as f:
                config = json.load(f)
        except (OSError, ValueError):
            config = {}

    header, excluded, sections, terms, selfcheck = parse_outline(text)

    if not header.get('thesis'):
        violations.append('header: missing \u5168\u6587\u6838\u5fc3\u95ee\u9898')
    if header.get('total_sections') is None:
        violations.append('header: \u603b\u8282\u6570 missing or not a number')
    if header.get('total_budget') is None:
        violations.append('header: \u603b\u5b57\u6570\u9884\u7b97 missing or not a number')

    seen_ks = set()
    for sec in sections:
        if sec['k'] in seen_ks:
            violations.append('duplicate section number %d in outline'
                              % sec['k'])
        seen_ks.add(sec['k'])
    if header.get('total_sections') is not None and len(sections) != header['total_sections']:
        violations.append('section count %d != declared \u603b\u8282\u6570 %d'
                          % (len(sections), header['total_sections']))

    objection_sections = []
    budget_sum = 0
    for sec in sections:
        k = sec['k']
        f = sec['fields']
        if args.require_stages and any(not f.get(key) for key, label in OPTIONAL_FIELDS):
            violations.append('section %d: missing stage label/short name' % k)
        if f.get('stage_short') and len(re.findall(r'[\u3400-\u9fff]', f['stage_short'])) > 6:
            violations.append('section %d: stage_short exceeds 6 CJK' % k)
        for key, label in SECTION_FIELDS:
            if key not in f or not f[key]:
                violations.append('section %d: missing field %s' % (k, label))
        # anchors
        anchors = parse_anchors(f.get('anchors_raw', ''))
        sec['anchors'] = anchors
        if not anchors:
            violations.append('section %d: no valid anchor range' % k)
        for a, b in anchors:
            if a < 1 or b > n_paras or a > b:
                violations.append('section %d: anchor P%d-P%d out of range [1,%d]'
                                  % (k, a, b, n_paras))
        # budget
        b_raw = f.get('budget_raw', '')
        m = re.search(r'(\d+)', b_raw)
        if m:
            sec['budget'] = int(m.group(1))
            budget_sum += sec['budget']
        else:
            sec['budget'] = None
            violations.append('section %d: budget not a number: %r' % (k, b_raw))
        if OBJECTION_MARK in f.get('chain_role', ''):
            objection_sections.append(k)
        # split prohibited list on ；/;
        sec['prohibited'] = [x.strip() for x in re.split(r'[\uff1b;]\s*', f.get('prohibited_raw', '')) if x.strip()]

    # v2.1: every numbered paragraph must belong to exactly one section or be declared in 未纳入内容
    assigned, overlaps = {}, []
    for sec in sections:
        for a, b in sec.get('anchors', []):
            for number in range(max(a, 1), min(b, n_paras) + 1):
                if number in assigned and assigned[number] != sec['k']:
                    overlaps.append((number, assigned[number], sec['k']))
                assigned.setdefault(number, sec['k'])
    declared = set()
    for entry in excluded:
        for first, last in re.findall(r'P(\d+)(?:\s*[\-\u2013\u2014]\s*P?(\d+))?', entry):
            declared.update(range(int(first), int(last or first) + 1))
    heading_like = set()
    for match in re.finditer(r'^\[P(\d+)\]\s*(.*)$', numbered, flags=re.M):
        body = match.group(2).strip()
        if body.startswith('#') or count_source_units(body, source_language(args.numbered)) <= 5:
            heading_like.add(int(match.group(1)))
    missing = sorted(set(range(1, n_paras + 1)) - set(assigned) - declared)
    hard = [m for m in missing if m not in heading_like]
    if hard:
        violations.append('source paragraphs in no section anchor and not declared under 未纳入内容: ' + ', '.join('P%d' % m for m in hard[:30]) + (' ...' if len(hard) > 30 else ''))
    soft = [m for m in missing if m in heading_like]
    if soft:
        advisories.append('heading-like paragraphs unassigned (ok if titles): ' + ', '.join('P%d' % m for m in soft[:20]))
    if overlaps:
        advisories.append('paragraphs anchored by two sections (main-section rule): ' + ', '.join('P%d(s%d,s%d)' % o for o in overlaps[:20]))
    if len(objection_sections) > 1:
        violations.append('strongest objection carried by %d sections (must be at most 1): %s'
                          % (len(objection_sections), objection_sections))
    elif not objection_sections:
        advisories.append('no section marked with 含最强异议 (acceptable for narrative/expository chapters; verify if source has a central objection)')

    total_words = config.get('total_words')
    if total_words:
        if not (1.0 * total_words <= budget_sum <= 1.2 * total_words):
            destination = advisories if args.advisory_budget else violations
            destination.append('budget sum %d outside [%.0f, %.0f] (config total_words=%d)'
                              % (budget_sum, total_words, 1.2 * total_words, total_words))

    # self-check table: every a./b./c./d. line must say 通过, not 不通过
    check_items = [s for s in selfcheck if re.match(r'^[a-d][\.\u3001]', s)]
    if len(check_items) < 4:
        violations.append('self-check table incomplete (%d/4 items)' % len(check_items))
    neg_words = ('\u4e0d\u901a\u8fc7', '\u672a\u901a\u8fc7',
                 '\u6ca1\u901a\u8fc7', '\u5c1a\u672a\u901a\u8fc7')
    for item in check_items:
        if any(w in item for w in neg_words) or ('\u901a\u8fc7' not in item):
            violations.append('self-check failed: %s' % item)

    ok = not violations
    # The orchestrator accepts only a validated outline; never leave stale state.
    outline = {
        'ok': ok,
        'thesis': header.get('thesis', ''),
        'total_sections': len(sections),
        'total_budget': header.get('total_budget'),
        'excluded': excluded,
        'sections': [
            {
                'k': s['k'],
                'title': s['title'],
                'stage_id': s['k'],
                'stage_label': s['fields'].get('stage_label') or s['title'],
                'stage_short': s['fields'].get('stage_short') or s['title'][:6],
                'position': s['fields'].get('position', ''),
                'sub_question': s['fields'].get('sub_question', ''),
                'inherits': s['fields'].get('inherits', ''),
                'core_content': s['fields'].get('core_content', ''),
                'conclusion': s['fields'].get('conclusion', ''),
                'chain_role': s['fields'].get('chain_role', ''),
                'has_strongest_objection': OBJECTION_MARK in s['fields'].get('chain_role', ''),
                'anchors': s.get('anchors', []),
                'prohibited': s.get('prohibited', []),
                'open_question': s['fields'].get('open_question', ''),
                'budget': s.get('budget'),
            } for s in sections
        ],
        'term_table': terms,
    }
    import os
    if ok:
        with io.open(args.out_json, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(outline, f, ensure_ascii=False, indent=1)
    elif os.path.exists(args.out_json):
        os.unlink(args.out_json)

    print(json.dumps({'ok': ok, 'violations': violations,
                      'advisories': advisories,
                      'outline_json': args.out_json if ok else None},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

