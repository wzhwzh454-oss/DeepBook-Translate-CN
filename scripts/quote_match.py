"""The source-quote matcher shared by checks and focused diagnosis."""
import difflib
import re


def compact_map(text):
    chars, offsets = [], []
    for index, char in enumerate(text):
        if not char.isspace():
            folded = char.casefold()
            chars.extend(folded)
            offsets.extend([index] * len(folded))
    return ''.join(chars), offsets


def match_quote(quote, paragraph, mapping=None):
    needle, _ = compact_map(quote)
    source, offsets = compact_map(paragraph)
    if not needle:
        return None
    start = source.find(needle)
    if start >= 0:
        return {'mode': 'literal', 'start': offsets[start], 'end': offsets[start + len(needle) - 1] + 1}
    # v2.1: punctuation / quote / dash / ellipsis / soft-hyphen / NFKC tolerant fallback.
    from bt_common import match_fold
    folded_quote, _ = match_fold(quote)
    folded_para, folded_offsets = match_fold(paragraph)
    if len(folded_quote) >= 12:
        hit = folded_para.find(folded_quote)
        if hit >= 0:
            begin = folded_offsets[hit]
            end = folded_offsets[hit + len(folded_quote) - 1] + 1
            return {'mode': 'normalized', 'start': begin, 'end': end,
                    'raw_fragment': paragraph[begin:end]}
    # Only exact paragraph maps from PDF geometry authorize optional wrap
    # hyphens. MD/TXT and stale maps use the unchanged literal rule.
    if not mapping or mapping.get('text') != paragraph:
        return None
    wraps = {record['start']: record for record in mapping.get('line_wraps', [])
             if paragraph[record['start']:record['start'] + 1] == '-'}
    if not wraps:
        return None
    masked = ''.join('\x00' if offsets[index] in wraps else char for index, char in enumerate(source))
    pattern = '\x00?'.join('(?:-|\x00)' if char == '-' else re.escape(char) for char in needle)
    found = re.search(pattern, masked)
    if found is None:
        return None
    begin, end = offsets[found.start()], offsets[found.end() - 1] + 1
    return {'mode': 'line-wrap-candidate', 'start': begin, 'end': end,
            'line_wraps': [record for position, record in wraps.items() if begin <= position < end],
            'raw_fragment': paragraph[begin:end]}


def quote_diagnostic(quote, paragraphs):
    """Short evidence of a failure, using the same whitespace/case policy."""
    needle, _ = compact_map(quote)
    best = None
    for identifier, paragraph in paragraphs.items():
        source, offsets = compact_map(paragraph)
        matcher = difflib.SequenceMatcher(None, needle, source, autojunk=False)
        common = matcher.find_longest_match(0, len(needle), 0, len(source))
        if best is None or common.size > best[0]:
            begin = max(0, common.b - common.a)
            end = min(len(source), begin + len(needle))
            fragment = source[begin:end]
            delta = difflib.SequenceMatcher(None, needle, fragment, autojunk=False)
            changes = [{'quote': needle[i:j][:60], 'source': fragment[a:b][:60]}
                       for op, i, j, a, b in delta.get_opcodes() if op != 'equal'][:3]
            original_start = offsets[begin] if offsets and begin < len(offsets) else 0
            original_end = offsets[end - 1] + 1 if end > begin else original_start
            best = (common.size, {'paragraph_id': identifier, 'quote': quote[:120],
                                 'source_fragment': paragraph[max(0, original_start-30):original_end+30][:180],
                                 'differences': changes})
    return best[1] if best else {'quote': quote[:120], 'source_fragment': '', 'differences': [], 'reason': 'no valid cited paragraph'}

