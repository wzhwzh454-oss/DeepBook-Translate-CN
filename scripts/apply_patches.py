# -*- coding: utf-8 -*-
"""apply_patches.py — apply P5 patch list to merged-draft-marked.md.

Rules (per SKILL.md S4):
- split each patch line on the first 4 '｜' into 5 fields:
  节号｜规则号｜操作｜原文引文｜替换文本
  (a 4-field line is accepted only when 操作 is 删除, implying empty
   replacement; any other parse failure is skipped + logged, never guessed)
- quote located after whitespace normalization; must be unique within its
  section — not unique / not found -> skip + patch_log
- overlapping quotes -> keep the earlier patch, skip the later one
- appendix (everything from the first line starting with 附录) is returned
  raw for the orchestrator to route into state

Usage:
  python3 apply_patches.py --patches workspace/patches.md \
      --marked workspace/merged-draft-marked.md \
      --out workspace/merged-final.md

Output (stdout JSON): {"ok": bool, "violations": [...], "applied": [...],
                       "patch_log": [...], "appendix": str}
"""
import argparse
import io
import json
import re
import sys
import textutil
from bt_common import write_text_atomic
from microedit import check_microedit, check_semantic_preservation

SEP = '\uff5c'  # ｜
OPS = ('删除', '替换', '缝合', '分段', '插入')
SEC_MARK_RE = re.compile(r'^\u3010\u7b2c(\d+)\u8282\u3011\s*$')


def split_marked(text):
    """Return ordered list of (k, body) sections from the marked draft."""
    sections = []
    cur_k = None
    buf = []
    for line in text.splitlines():
        m = SEC_MARK_RE.match(line.strip())
        if m:
            if cur_k is not None:
                sections.append((cur_k, '\n'.join(buf).strip('\n')))
            cur_k = int(m.group(1))
            buf = []
        elif cur_k is not None:
            buf.append(line)
    if cur_k is not None:
        sections.append((cur_k, '\n'.join(buf).strip('\n')))
    return sections


def parse_patch_line(line):
    """Return dict or None (unparseable)."""
    s = line.strip()
    if not s or s.startswith('\u9644\u5f55'):  # 附录
        return None
    fields = s.split(SEP, 4)
    if len(fields) == 5:
        sec_f, rule_f, op_f, quote_f, repl_f = fields
    elif len(fields) == 4 and fields[2].strip() in ('删除', '分段'):
        sec_f, rule_f, op_f, quote_f = fields
        repl_f = ''
    else:
        return None
    m = re.search(r'(\d+)', sec_f)
    if not m:
        return None
    op = op_f.strip()
    if op not in OPS:
        return None
    if not quote_f.strip():
        return None
    return {'k': int(m.group(1)), 'rule': rule_f.strip(), 'op': op,
            'quote': quote_f.strip(), 'replacement': repl_f.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--patches', required=True)
    ap.add_argument('--marked', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--profile', choices=('legacy', 'v2'), default='legacy')
    ap.add_argument('--terms-json')
    ap.add_argument('--out-marked')
    ap.add_argument('--partial-ok', action='store_true',
                    help='write the output even if some patches were skipped (default: all-or-nothing)')
    args = ap.parse_args(argv)

    violations = []
    try:
        with io.open(args.patches, encoding='utf-8') as f:
            patch_text = f.read()
        with io.open(args.marked, encoding='utf-8') as f:
            marked = f.read()
    except OSError as e:
        print(json.dumps({'ok': False, 'violations': ['cannot read input: %s' % e]},
                         ensure_ascii=False))
        return 1

    # separate patch lines from appendix
    lines = patch_text.splitlines()
    appendix_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith('\u9644\u5f55'):  # 附录
            appendix_start = i
            break
    patch_lines = lines[:appendix_start] if appendix_start is not None else lines
    appendix = '\n'.join(lines[appendix_start:]).strip() if appendix_start is not None else ''

    patches = []
    patch_log = []
    for line in patch_lines:
        if not line.strip():
            continue
        p = parse_patch_line(line)
        if p is None:
            patch_log.append({'line': line.strip()[:80], 'status': 'skipped',
                              'reason': 'parse failure'})
            continue
        patches.append(p)

    if not patches:
        # zero patches is a legitimate outcome (P5 may find nothing to fix);
        # only flag a violation when patch-looking lines existed but none
        # could be parsed
        attempted = [l for l in patch_lines if l.strip() and SEP in l]
        if attempted:
            violations.append('no parseable patch lines found')

    # 重复节标记会让 dict() 静默丢弃先出现的正文、order 再重复拼接后者：
    # 以首次出现为准并记违规，避免内容丢失/重复而无告警。
    raw_sections = split_marked(marked)
    if not raw_sections and marked.strip():
        # 单小节兼容模式：输入文件未带【第k节】标记时，以补丁中节号或第1节为准
        target_k = patches[0]['k'] if patches else 1
        raw_sections = [(target_k, marked.strip())]

    sections = {}
    order = []
    for k, body in raw_sections:
        if k in sections:
            violations.append('duplicate section marker '
                              '\u3010\u7b2c%d\u8282\u3011 in marked draft' % k)
            continue
        sections[k] = body
        order.append(k)
    accepted = {}   # k -> list of (a, b, replacement)
    applied = []
    terms = []
    if args.terms_json:
        with io.open(args.terms_json, encoding='utf-8') as terms_file:
            terms_data = json.load(terms_file)
        terms = terms_data.get('term_ledger', []) if isinstance(terms_data, dict) else terms_data

    for p in patches:
        k, quote, op = p['k'], p['quote'], p['op']
        entry = {'k': k, 'rule': p['rule'], 'op': op, 'quote': quote}
        if k not in sections:
            entry.update(status='skipped', reason='section %d not in marked draft' % k)
            patch_log.append(entry)
            continue
        spans = textutil.find_norm_spans(sections[k], quote)
        if not spans:
            entry.update(status='skipped', reason='quote not found')
            patch_log.append(entry)
            continue
        spans = [s for s in spans if not re.search(r'\n\s*\n', sections[k][s[0]:s[1]])]
        if not spans:
            entry.update(status='skipped', reason='quote spans a paragraph boundary')
            patch_log.append(entry)
            continue
        if len(spans) > 1:
            entry.update(status='skipped', reason='quote not unique (%d hits)' % len(spans))
            patch_log.append(entry)
            continue
        a, b = spans[0]
        replacement = p['replacement']
        if args.profile == 'v2':
            replacement = replacement.replace('\\n', '\n')
            valid_operation = ((p['rule'] == 'T10' and op == '替换')
                               or (p['rule'] == 'T11' and op == '分段' and not replacement)
                               or (p['rule'] == 'T12' and op in ('插入', '替换') and bool(replacement))
                               or (p['rule'] == 'T13' and op in ('替换', '缝合') and bool(replacement))
                               or (p['rule'] == 'T14' and op == '替换' and bool(replacement)))
            if p['rule'] in ('T10', 'T11', 'T12', 'T13', 'T14') or op in ('分段', '插入'):
                if not valid_operation:
                    entry.update(status='skipped', reason='v2 rule/operation mismatch')
                    patch_log.append(entry)
                    continue
            if p['rule'] == 'T10' and not check_microedit(sections[k][a:b], replacement, terms):
                entry.update(status='skipped', reason='microedit rule')
                patch_log.append(entry)
                continue
            if p['rule'] in ('T13', 'T14') and not check_semantic_preservation(sections[k][a:b], replacement, terms):
                entry.update(status='skipped', reason='semantic operator or terminology preservation')
                patch_log.append(entry)
                continue
            if op == '分段':
                if not re.search(r'[。？！][”」』"）)]*$', sections[k][a:b]):
                    entry.update(status='skipped', reason='paragraph break is not at sentence end')
                    patch_log.append(entry)
                    continue
                replacement = sections[k][a:b] + '\n\n'
            elif op == '插入':
                replacement = sections[k][a:b] + replacement
        elif op in ('分段', '插入') or p['rule'] in ('T10', 'T11', 'T12', 'T13', 'T14'):
            entry.update(status='skipped', reason='v2 operation requires --profile v2')
            patch_log.append(entry)
            continue
        overlaps = any(not (b <= a2 or a >= b2) for a2, b2, _ in accepted.get(k, []))
        if overlaps:
            entry.update(status='skipped', reason='overlaps an earlier patch')
            patch_log.append(entry)
            continue
        accepted.setdefault(k, []).append((a, b, replacement))
        entry.update(status='applied')
        patch_log.append(entry)
        applied.append(entry)

    # apply bottom-up within each section
    for k, edits in accepted.items():
        txt = sections[k]
        for a, b, repl in sorted(edits, key=lambda e: e[0], reverse=True):
            txt = txt[:a] + repl + txt[b:]
        sections[k] = txt

    final = '\n\n'.join(sections[k] for k in order).strip('\n') + '\n'
    if args.profile == 'v2':
        violations.extend('%s: %s' % (entry.get('rule', 'patch'), entry['reason']) for entry in patch_log if entry['status'] == 'skipped')
    # all-or-nothing: a partially applied patch set cannot be re-run (applied quotes no longer exist)
    written = not violations or args.partial_ok
    if written:
        write_text_atomic(args.out, final)
        if args.out_marked:
            write_text_atomic(args.out_marked, '\n\n'.join('【第%d节】\n%s' % (number, sections[number]) for number in order) + '\n')

    ok = not violations
    print(json.dumps({'ok': ok, 'written': written, 'violations': violations, 'applied': applied,
                      'patch_log': patch_log, 'appendix': appendix},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())


def main_argv(argv):
    return main(argv)

