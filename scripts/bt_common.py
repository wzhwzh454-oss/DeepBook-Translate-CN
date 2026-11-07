# -*- coding: utf-8 -*-
"""bt_common.py — shared hardening primitives for book-translator (v2.1).

Stdlib only. Everything here exists to close a concrete defect found in the v2.0 review:
  * atomic / strict JSON state IO (generate_handover silently reset a corrupt ledger)
  * one canonical "final chapter" resolver (chapter-final.md vs merged-final.md ambiguity)
  * punctuation/quote/dash/NFKC tolerant provenance matching (quote_match only folded case+space)
  * English-leak scan for writer-facing sheets
  * term ledger merge (namespaced uids, drift = hard error) and a real dependency graph
    (Kahn layering + Tarjan SCC) instead of the two-bucket "topology" in merge_book.
"""
from copy import deepcopy
from language import LANG_PROFILES, get_lang_profile, detect_source_language, count_source_units, expected_zh_chars, source_language_leaks
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path


class StateError(RuntimeError):
    """Raised when persisted workflow state is missing/corrupt/inconsistent."""


# ----------------------------------------------------------------- hashing / IO
def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256_file(path):
    return sha256_text(Path(path).read_text(encoding='utf-8'))


def read_json_strict(path, default=None, required=False):
    """Read JSON; a *corrupt* file is an error (never silently replaced by `default`)."""
    p = Path(path)
    if not p.exists():
        if required:
            raise StateError('missing required state file: %s' % p)
        return default
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise StateError('corrupt JSON state %s (%s); restore %s.bak before continuing'
                         % (p, exc, p.name)) from exc


def write_text_atomic(path, text, backup=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if backup and p.exists():
        shutil.copy2(str(p), str(p) + '.bak')
    fd, tmp = tempfile.mkstemp(prefix=p.name + '.', suffix='.tmp', dir=str(p.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path, data, backup=True):
    payload = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    json.loads(payload)  # round-trip sanity before touching disk
    write_text_atomic(path, payload, backup=backup)


# ------------------------------------------------------- canonical chapter final
def resolve_chapter_final(chapter_dir):
    """Return (path_or_None, problems). chapter-final.md is canonical.

    v2.0 preferred chapter-final.md silently even when a newer P5-patched merged-final.md
    existed, so patched text never reached handover/delivery. Divergent twins are now an error.
    """
    base = Path(chapter_dir)
    canonical, twin = base / 'chapter-final.md', base / 'merged-final.md'
    problems = []
    if canonical.exists() and twin.exists():
        if canonical.read_text(encoding='utf-8').strip() != twin.read_text(encoding='utf-8').strip():
            problems.append('ambiguous final artifact: chapter-final.md and merged-final.md differ; '
                            'promote the approved one to chapter-final.md and delete the other')
        return canonical, problems
    if canonical.exists():
        return canonical, problems
    if twin.exists():
        return twin, problems
    return None, ['no chapter-final.md (or merged-final.md) in %s' % base]


# ------------------------------------------------------------ provenance matching
def match_fold(text):
    """Fold *text* to letters/digits/CJK only (NFKC + casefold, combining-mark aware).

    Returns (folded, offsets) where offsets[i] is the index in the ORIGINAL text of the
    cluster that produced folded[i]. Punctuation, quotes (’ vs '), dashes (— vs --),
    ellipsis, soft hyphens, zero-width characters and whitespace are all dropped, so a quote
    only has to agree on the actual words.
    """
    out, offsets = [], []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        for ch in unicodedata.normalize('NFKC', text[i:j]).casefold():
            if unicodedata.category(ch)[0] in 'LN' or unicodedata.category(ch) == 'Sm':
                out.append(ch)
                offsets.append(i)
        i = j
    return ''.join(out), offsets


def quote_long_enough(quote, min_chars=12):
    """A provenance quote must carry enough words to evidence anything (v2.0 accepted 'a')."""
    return len(match_fold(quote)[0]) >= min_chars


# ----------------------------------------------------------------- English leak scan
_EN_RUN = re.compile(r"(?:[A-Za-z][A-Za-z'\u2019\-]*[ \t,;:]*){%d,}")


def english_leaks(text, allow=(), min_words=6):
    """Return snippets of >= min_words consecutive English words (allow-listed terms removed).

    Used on writer-facing task sheets: the writer must never see English sentences.
    """
    cleaned = text
    for term in sorted({a for a in allow if a}, key=len, reverse=True):
        cleaned = re.sub(re.escape(term), ' ', cleaned, flags=re.I)
    pattern = re.compile(_EN_RUN.pattern % min_words)
    return [m.group(0).strip()[:120] for m in pattern.finditer(cleaned)]


# --------------------------------------------------------------- term ledger / graph
def term_uid(chapter, tid):
    return 'c%02d:%s' % (int(chapter), tid)


def norm_orig(orig, lang='en'):
    value = re.sub(r'[\s\-\u2010-\u2015]+', ' ', str(orig or '').strip('（）() ')).casefold().strip()
    words = []
    for word in value.split(' '):
        if lang == 'en' and len(word) > 4 and word.endswith('s') and not word.endswith(('ss', 'us', 'is', 'os', 'as', 'ys', 'es', 'ics')):
            word = word[:-1]
        words.append(word)
    return ' '.join(words)


def merge_plan_into_ledger(ledger, plan_terms, chapter):
    """Pure function. Returns (new_ledger, conflicts). Conflicts are HARD errors:
    nothing may be merged when the same original gets a second translation, or one Chinese
    name is claimed by two originals without an explicit `collision` note.
    """
    ledger = deepcopy(ledger)
    key_of = lambda t: norm_orig(t.get('orig'), t.get('source_lang', 'en'))
    by_orig = {key_of(t): t for t in ledger if t.get('orig')}
    by_zh = {t.get('zh'): t for t in ledger if t.get('zh')}
    conflicts, additions, local_uid = [], [], {}
    for term in plan_terms:
        zh = str(term.get('zh', '')).strip()
        orig = str(term.get('orig', '')).strip()
        if not zh:
            continue
        key = key_of(term)
        old = by_orig.get(key) if key else None
        if old is not None and old.get('zh') != zh:
            conflicts.append('drift: %r was locked as %r (ch%s) but ch%s plans %r'
                             % (orig, old.get('zh'), old.get('defined_in_chapter'), chapter, zh))
            continue
        same_zh = by_zh.get(zh)
        if same_zh is not None and key and key_of(same_zh) != key \
                and not term.get('collision'):
            conflicts.append('ambiguity: %r already denotes %r; ch%s uses it for %r (add `collision` to split senses)'
                             % (zh, same_zh.get('orig'), chapter, orig))
            continue
        if old is not None or same_zh is not None:
            target = old or same_zh
            target['alias_ban'] = sorted(set(target.get('alias_ban', [])) | set(term.get('alias_ban', [])))
            if not target.get('gloss') and term.get('gloss'):
                target['gloss'] = term['gloss']
            for field in ('source_lang', 'category', 'authority_sources', 'translation_note', 'analogy', 'orig_aliases'):
                if term.get(field) and not target.get(field):
                    target[field] = deepcopy(term[field])
            if term.get('id'):
                local_uid[term['id']] = target.get('uid') or term_uid(target.get('defined_in_chapter', chapter), target.get('id', '?'))
            continue
        uid = term_uid(chapter, term.get('id') or 'T%d' % (len(ledger) + len(additions) + 1))
        local_uid[term.get('id')] = uid
        additions.append({
            'uid': uid, 'id': term.get('id') or uid.split(':')[1], 'zh': zh, 'orig': orig,
            'level': term.get('level', '核心'), 'defined_in_chapter': int(chapter),
            **{field: deepcopy(term[field]) for field in ('source_lang', 'category', 'authority_sources', 'translation_note', 'analogy', 'orig_aliases', 'collision') if field in term},
            'locked': True, 'depends_on': list(term.get('depends_on', [])),
            'gloss': term.get('gloss', ''), 'role': term.get('role', ''),
            'alias_ban': list(term.get('alias_ban', [])), 'user_banned': list(term.get('user_banned', [])),
            'provenance': {'source': 'model_term_plan', 'chapter': int(chapter), 'user_confirmed': False},
        })
    if conflicts:
        return ledger, conflicts
    for item in additions:  # rewrite chapter-local dependency ids to global uids
        item['depends_on'] = [local_uid.get(dep, dep) for dep in item['depends_on']]
    return ledger + additions, conflicts


def analyze_term_graph(terms):
    """Real dependency analysis over a (namespaced) ledger.

    Returns dict(layers, cycles, unresolved, forward_refs, blocked, edges).
    layers[i] = uids whose dependencies all sit in layers < i (Kahn layering);
    cycles = strongly connected components with >1 node or a self loop (Tarjan).
    """
    nodes = {}
    for t in terms:
        uid = t.get('uid') or term_uid(t.get('defined_in_chapter', 0), t.get('id', '?'))
        nodes[uid] = t
    by_zh = {t.get('zh'): uid for uid, t in nodes.items() if t.get('zh')}
    by_orig = {norm_orig(t.get('orig')): uid for uid, t in nodes.items() if t.get('orig')}

    def resolve(dep, chapter):
        if dep in nodes:
            return dep
        local = term_uid(chapter, dep)
        if local in nodes:
            return local
        name = dep[7:] if dep.startswith('ledger:') else dep
        return by_zh.get(name) or by_orig.get(norm_orig(name))

    edges = {uid: set() for uid in nodes}
    unresolved, forward = [], []
    for uid, t in nodes.items():
        for dep in t.get('depends_on') or []:
            target = resolve(dep, t.get('defined_in_chapter', 0))
            if target is None:
                unresolved.append({'term': uid, 'depends_on': dep})
                continue
            edges[uid].add(target)
            if nodes[target].get('defined_in_chapter', 0) > t.get('defined_in_chapter', 0):
                forward.append({'term': uid, 'depends_on': target})
    # Tarjan SCC
    index, low, on, stack, counter, sccs = {}, {}, set(), [], [0], []

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(edges[v]):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(sorted(comp))

    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    for v in sorted(nodes):
        if v not in index:
            strong(v)
    cycles = [c for c in sccs if len(c) > 1 or c[0] in edges[c[0]]]
    level, layers, remaining = {}, [], set(nodes)
    while remaining:
        ready = sorted(v for v in remaining if all(d in level for d in edges[v]))
        if not ready:
            break
        for v in ready:
            level[v] = len(layers)
        layers.append(ready)
        remaining -= set(ready)
    return {'layers': layers, 'cycles': cycles, 'unresolved': unresolved,
            'forward_refs': forward, 'blocked': sorted(remaining),
            'edges': {k: sorted(v) for k, v in edges.items()}, 'nodes': nodes}


def term_graph_mermaid(analysis):
    nodes = analysis['nodes']
    ids = {uid: 'n%d' % i for i, uid in enumerate(sorted(nodes))}
    lines = ['graph TD']
    for uid in sorted(nodes):
        label = (nodes[uid].get('zh') or uid).replace('"', "'")
        lines.append('    %s["%s"]' % (ids[uid], label))
    for uid, deps in sorted(analysis['edges'].items()):
        for dep in deps:
            lines.append('    %s --> %s' % (ids[dep], ids[uid]))
    return '\n'.join(lines)
