# -*- coding: utf-8 -*-
"""Heuristic parity checks for quantifier, negation, condition and modal cues."""
import re

NON_NEGATIVE_PHRASES = re.compile(
    r'不但|不仅|不单|不光|不止|非但|不妨|不难|不外乎|不失为|不啻|不言而喻|'
    r'不断|不久|不时|不日|不凡|不菲|不俗|不二|不然|不免|不易|'
    r'无论|不论|不管|无非|无一例外|无微不至|无所不在|无处不在|无穷|无限|无价|无比|无数|'
    r'未来|未免|非常|非凡|是非|淹没|沉没|埋没|出没|覆没|吞没|没收|没落|辱没|泯没'
)

NEGATION_CUES_RE = re.compile(
    r'并非|不是|没有|并不|未曾|从不|绝不|决不|无法|不能|不会|不再|并未|尚未|不可|'
    r'未必|不一定|不必然|不见得|否认|拒绝|排除|缺乏|缺少|免于|远非|毫无|并无|尚无|'
    r'没(?:有|能|法|收到|给出|提供|支持|证明|发现|看到|得到|实现|解决|达到|完成|交代)|'
    r'无(?:法|从|须|需|关|效|视|意|力|权|益|助|异|疑|涉|凭|据|可能|条件|根据|证据|理由|意义|必要)|'
    r'(?<![淹沉埋出覆吞辱泯])没(?![收落])[\u4e00-\u9fff]|'
    r'不(?![但仅单光止妨外失啻断难久时日凡菲俗二然言易免同])[\u4e00-\u9fff]|'
    r'未(?![来免然])[\u4e00-\u9fff]|'
    r'非(?![常凡但])[\u4e00-\u9fff]'
)

DOUBLE_NEGATION_RE = re.compile(
    r'(?:并非|不是)\s*不可能|'
    r'(?:并非|不是)\s*(?:没有|没)|'
    r'不能不|不得不|不可不|不敢不|不无|无不(?!良)|莫不|未尝(?:不|没|没有)'
)

DIFFICULTY_RE = re.compile(r'难以|很难|难于|不易|未易')

CLASSES = {
    'universal': r'所有|每个|每一|任何|一切|凡是|全部|无一例外|总是',
    'existential': r'有些|某些|有的|至少有|存在',
    'negation': NEGATION_CUES_RE.pattern,
    'necessary_cond': r'只有|仅当|除非|唯有|必须',
    'sufficient_cond': r'只要|如果|假如|一旦|倘若',
    'iff': r'当且仅当|充要|恰好当',
    'possible': r'(?<![不无没])(?:可能|能够|可以)|或许|也许|似乎|大概|未必|不一定|不必然|不见得',
    'necessary': r'必然|一定|必定|不可避免|无疑',
    'limiter': r'至多|至少|仅仅|仅|只是|尚未',
}

STRENGTHENING = ('universal', 'necessary', 'iff', 'necessary_cond')

UNIV = r'(?:所有|每个|每一|任何|一切)'
NEGW = r'(?:都|全)?(?:不|没有|无|未)'
POSS_NOT = r'(?:(?:可能|或许|也许|似乎|大概)[^，。；！？]{0,3}(?:不|没|未|非)|未必|不一定|不必然|不见得)'
IMPOSSIBLE_OR_NEC_NOT = (
    r'(?<![非是])不可能|没可能|绝无可能|毫无可能|'
    r'(?:必然|一定|必定)[^，。；！？]{0,3}(?:不|没|未|非)'
)
INVERSIONS = (
    (r'(?:并非|不是)' + UNIV, UNIV + r'[^，。；！？]{0,10}' + NEGW + r'(?![论仅同])', r'并非|不是|不都是|不全是',
     'hard: scope inversion: partial negation (并非所有) rendered as universal negation (所有都不)'),
    (UNIV + r'[^，。；！？]{0,10}' + NEGW + r'(?![论仅同])', r'(?:并非|不是)' + UNIV, r'(?!)',
     'advisory: scope inversion: universal negation rendered as partial negation'),
    (r'只有|仅当|除非|唯有', r'只要|如果|假如|一旦', r'只有|仅当|除非|唯有|才',
     'hard: scope inversion: necessary condition rendered as sufficient condition'),
    (r'只要|一旦', r'只有|仅当|除非|唯有', r'只要|一旦|就',
     'advisory: scope inversion: sufficient condition rendered as necessary condition'),
    (POSS_NOT, IMPOSSIBLE_OR_NEC_NOT, POSS_NOT,
     'hard: modal inversion: contingent negation rendered as modal impossibility'),
    (IMPOSSIBLE_OR_NEC_NOT, POSS_NOT, IMPOSSIBLE_OR_NEC_NOT,
     'hard: modal inversion: modal impossibility rendered as contingent negation'),
)


def _requirement_text(statement, qualifiers):
    statement = statement or ''
    if qualifiers in (None, '', '无'):
        return statement
    parts = [part for part in re.split(r'[、，,;；\s]+', str(qualifiers).strip()) if part]
    if parts and all(part in statement for part in parts):
        return statement
    return '%s %s' % (statement, qualifiers)


def _normalize_double_negation(text):
    def replace(match):
        phrase = match.group(0)
        if '不可能' in phrase:
            return '可能'
        if phrase in ('无不', '莫不'):
            return '都'
        if phrase.startswith('未尝') or phrase == '不无':
            return '有'
        if '没有' in phrase or '没' in phrase or phrase == '不无':
            return '有'
        return '必须'

    return DOUBLE_NEGATION_RE.sub(replace, text or '')


def _has_double_negation(text):
    return bool(DOUBLE_NEGATION_RE.search(text or ''))


def _negation_match(text):
    # Exclusions affect only negation scanning; other operator classes see the original phrase.
    searchable = NON_NEGATIVE_PHRASES.sub(' ', text or '')
    return NEGATION_CUES_RE.search(searchable)


def operator_parity(statement, qualifiers, evidence_context):
    """Return heuristic issues between a bearing point and its claimed evidence."""
    requirement = _requirement_text(statement, qualifiers)
    evidence_context = evidence_context or ''
    req_double = _has_double_negation(requirement)
    ev_double = _has_double_negation(evidence_context)
    req_norm = _normalize_double_negation(requirement)
    ev_norm = _normalize_double_negation(evidence_context)
    issues = []

    req_neg = _negation_match(req_norm)
    ev_neg = _negation_match(ev_norm)
    if req_double and not ev_double and ev_neg:
        issues.append('hard: scope inversion: double negation rendered as direct negation')
    elif ev_double and not req_double and req_neg:
        issues.append('hard: scope inversion: direct negation rendered as double negation')
    elif req_neg and not ev_neg:
        req_diff = DIFFICULTY_RE.search(req_norm)
        ev_diff = DIFFICULTY_RE.search(ev_norm)
        if ev_diff:
            issues.append('negation/difficulty shift: point carries negation %r but evidence uses difficulty cue %r'
                          % (req_neg.group(0), ev_diff.group(0)))
        else:
            issues.append('negation: point carries %r but evidence has no negation cue' % req_neg.group(0))
    elif ev_neg and not req_neg:
        req_diff = DIFFICULTY_RE.search(req_norm)
        if req_diff:
            issues.append('negation/difficulty shift: point carries difficulty cue %r but evidence uses categorical negation %r'
                          % (req_diff.group(0), ev_neg.group(0)))
        else:
            issues.append('negation: evidence introduces %r absent from the point (possible polarity reversal)'
                          % ev_neg.group(0))

    for name, pattern in CLASSES.items():
        if name == 'negation':
            continue
        in_req, in_ev = re.search(pattern, req_norm), re.search(pattern, ev_norm)
        if in_req and not in_ev:
            issues.append('%s: point carries %r but evidence has no %s cue' % (name, in_req.group(0), name))
        if name in STRENGTHENING and in_ev and not in_req:
            issues.append('%s: evidence introduces %r absent from the point (possible strengthening)'
                          % (name, in_ev.group(0)))

    for req_pat, ev_pat, ok_pat, label in INVERSIONS:
        if re.search(req_pat, req_norm) and re.search(ev_pat, ev_norm) \
                and not re.search(ok_pat, ev_norm):
            issues.append(label)

    if re.search(CLASSES['possible'], req_norm) and re.search(CLASSES['necessary'], ev_norm):
        issues.append('hard: modal inversion: possibility rendered as necessity')

    req_diff = DIFFICULTY_RE.search(req_norm)
    ev_diff = DIFFICULTY_RE.search(ev_norm)
    if req_diff and not ev_diff and not ev_neg:
        issues.append('difficulty: point carries %r but evidence has no difficulty or negation cue' % req_diff.group(0))
    return issues
