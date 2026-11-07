# -*- coding: utf-8 -*-
"""textutil.py — shared utilities for the long-article pipeline.

Deterministic, stdlib-only. Provides:
- whitespace normalization (spaces / tabs / newlines / full-width spaces)
- CJK character counting
- Chinese sentence splitting (。？！ boundaries; trailing closing quotes
  attach to the preceding sentence; ；does NOT split)
- normalized-search helpers that map matches back to original spans
"""
import re

WS_RE = re.compile(r'[\s\u3000]+')


def report_summary(result, report, limit=4):
    return {'ok': result['ok'], 'violations': len(result.get('violations', [])),
            'samples': [str(issue)[:240] for issue in result.get('violations', [])[:limit]],
            'advisory_count': len(result.get('advisories', [])),
            'advisories': [str(issue)[:240] for issue in result.get('advisories', [])[:3]], 'report': str(report)}


SENT_END = set('\u3002\uff1f\uff01')            # 。 ？ ！
QUOTE_TAIL = set('\u201d\u2019"\u300d\u300f\uff09\u3015\u300b\u3009')  # " ’ " 」 』 ） 〕 》 〉


def normalize_ws(text):
    """Collapse every whitespace run (incl. full-width space) to one ASCII space."""
    return WS_RE.sub(' ', text).strip()


def reader_plain_text(text):
    """Remove display-only emphasis; preserve every word, negation and math symbol."""
    text = re.sub(r"(?m)^#{1,6}[^\n]*(?:\n|$)", "", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda match: match.group(1) or match.group(2), text, flags=re.S)
    return text


def compact(text):
    """Remove ALL whitespace (incl. full-width space) from *text*."""
    return ''.join(ch for ch in text if not ch.isspace() and ch != '\u3000')


def cjk_count(text):
    """Count CJK ideographs (main block + extension A)."""
    return sum(1 for ch in text
               if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf')


def split_sentences_spans(text):
    """Split *text* into sentences; return list of (start, end) spans.

    Boundary chars are 。？！. Closing quote characters immediately following a
    boundary attach to that sentence. ；never splits. Leading/trailing
    whitespace of each sentence span is excluded.
    """
    spans = []
    n = len(text)
    i = 0
    start = None
    while i < n:
        ch = text[i]
        if start is None:
            if not ch.isspace() and ch != '\u3000':
                start = i
            i += 1
            continue
        if ch in SENT_END:
            end = i + 1
            while end < n and text[end] in QUOTE_TAIL:
                end += 1
            spans.append((start, end))
            start = None
            i = end
            continue
        i += 1
    if start is not None:
        spans.append((start, n))
    return spans


def split_sentences(text):
    """Return the sentence strings of *text* (see split_sentences_spans)."""
    return [text[a:b] for a, b in split_sentences_spans(text)]


def split_paragraphs(text):
    """Split into paragraphs on blank lines; return list of paragraph strings."""
    blocks = re.split(r'\n\s*\n', text)
    return [b.strip() for b in blocks if b.strip()]


def norm_index_map(text):
    """Build the normalized form of *text* plus a span map back to the original.

    Returns (norm, spans) where spans[j] == (orig_start, orig_end_exclusive)
    for the j-th normalized character. Every whitespace run collapses to a
    single ASCII space whose span covers the whole run.
    """
    norm_chars = []
    spans = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch == '\u3000':
            j = i
            while j < n and (text[j].isspace() or text[j] == '\u3000'):
                j += 1
            norm_chars.append(' ')
            spans.append((i, j))
            i = j
        else:
            norm_chars.append(ch)
            spans.append((i, i + 1))
            i += 1
    return ''.join(norm_chars), spans


def compact_index_map(text):
    """Like norm_index_map but DROPS all whitespace characters.

    Returns (compact, spans) where spans[j] is the original span of the
    j-th non-whitespace character.
    """
    compact_chars = []
    spans = []
    for i, ch in enumerate(text):
        if ch.isspace() or ch == '\u3000':
            continue
        compact_chars.append(ch)
        spans.append((i, i + 1))
    return ''.join(compact_chars), spans


def find_norm_spans(text, quote):
    """Find all occurrences of *quote* in *text* under whitespace-insensitive
    matching. Both sides are compacted (all whitespace removed) before
    matching, so spacing / newline differences never prevent a match.

    Returns a list of original (start, end_exclusive) spans.
    """
    ctext, spans = compact_index_map(text)
    cquote = compact(quote)
    if not cquote:
        return []
    out = []
    pos = 0
    while True:
        idx = ctext.find(cquote, pos)
        if idx < 0:
            break
        start = spans[idx][0]
        end = spans[idx + len(cquote) - 1][1]
        out.append((start, end))
        pos = idx + len(cquote)
    return out


def is_subsequence(needle, haystack):
    """True if *needle* is a character subsequence of *haystack*."""
    it = iter(haystack)
    return all(ch in it for ch in needle)

