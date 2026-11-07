"""Six source languages and source-text checks. Standard library only."""
import re
import unicodedata

LANG_PROFILES = {
    'en': {'name': '英语', 'unit': 'word', 'to_zh_chars': 1.70, 'chapter': r'Chapter|Part|Book', 'back': r'Notes|Endnotes|Bibliography|References|Works Cited|Index|Acknowledg(?:e)?ments|Glossary'},
    'de': {'name': '德语', 'unit': 'word', 'to_zh_chars': 2.15, 'chapter': r'Kapitel|Teil|Buch|Abschnitt', 'back': r'Anmerkungen|Endnoten|Literatur(?:verzeichnis)?|Bibliographie|Register|Index|Danksagung|Glossar'},
    'fr': {'name': '法语', 'unit': 'word', 'to_zh_chars': 1.45, 'chapter': r'Chapitre|Partie|Livre', 'back': r'Notes|Bibliographie|Références|Index|Remerciements|Glossaire'},
    'es': {'name': '西班牙语', 'unit': 'word', 'to_zh_chars': 1.45, 'chapter': r'Capítulo|Parte|Libro', 'back': r'Notas|Bibliografía|Referencias|Índice|Agradecimientos|Glosario'},
    'ru': {'name': '俄语', 'unit': 'word', 'to_zh_chars': 1.95, 'chapter': r'Глава|Часть|Книга|Раздел', 'back': r'Примечания|Библиография|Литература|Указатель|Благодарности|Глоссарий'},
    'ja': {'name': '日语', 'unit': 'char', 'to_zh_chars': 0.72, 'chapter': r'第[一二三四五六七八九十百千〇零\d]+[章部編篇]', 'back': r'注|註|参考文献|文献一覧|索引|あとがき|謝辞|用語集'},
}
FUNCTION_WORDS = {
    'en': 'the and that whether however therefore which because these their with from',
    'de': 'der die das und nicht ist sind jedoch durch eine einer wird auch sich',
    'fr': 'le la les des du et une dans est sont que qui avec pour',
    'es': 'el los las del una que por pero para como este esta son también',
}

def get_lang_profile(lang='en'):
    code = str(lang or 'en').lower().strip()
    if code not in LANG_PROFILES:
        raise ValueError('unsupported source language: ' + code)
    return LANG_PROFILES[code]

def source_tokens(text):
    return re.findall(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", unicodedata.normalize('NFC', text).casefold())

def detect_language_details(text):
    # Sample across the book instead of letting a foreign-language preface dominate.
    text = text or ''
    step = max(1, len(text) // 5)
    sample = '\n'.join(text[i:i + 8000] for i in range(0, len(text), step))[:40000]
    letters = sum(ch.isalpha() for ch in sample)
    kana = len(re.findall(r'[ぁ-ヿ]', sample))
    cyrillic = len(re.findall(r'[Ѐ-ԯ]', sample))
    if kana >= 3 and kana / max(letters, 1) >= 0.04:
        return {'language': 'ja', 'confidence': 'high', 'basis': 'kana across source samples'}
    if cyrillic >= 8 and cyrillic / max(letters, 1) >= 0.35:
        return {'language': 'ru', 'confidence': 'high', 'basis': 'majority Cyrillic source text'}
    words = source_tokens(sample)
    from collections import Counter
    counts = Counter(words)
    scores = {code: sum(min(counts[w], 15) for w in hints.split()) for code, hints in FUNCTION_WORDS.items()}
    # Heading cues are helpful when a chapter is short, but never override a whole book.
    for code in scores:
        scores[code] += 3 * len(re.findall(r'^\s*#{0,4}\s*(?:' + LANG_PROFILES[code]['chapter'] + r')\s', sample, re.M | re.I))
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, runner = ranked[:2]
    confidence = 'high' if scores[best] >= 8 and scores[best] >= scores[runner] * 1.4 else 'low'
    return {'language': best if scores[best] else 'en', 'confidence': confidence, 'basis': 'function words and headings', 'scores': scores}

def detect_source_language(text):
    return detect_language_details(text)['language']

def count_source_units(text, lang='en'):
    if get_lang_profile(lang)['unit'] == 'char':
        return sum(ch.isalnum() for ch in text)
    return len(source_tokens(text))

def expected_zh_chars(count, lang='en'):
    return float(count) * get_lang_profile(lang)['to_zh_chars']

def mask_allowed(text, allow=()):
    cleaned = text
    for term in sorted({str(a) for a in allow if a}, key=len, reverse=True):
        # Latin terms must not be removed from inside a different word.
        boundary = r'(?<!\w)' if re.match(r'[A-Za-zÀ-ɏ]', term) else ''
        end = r'(?!\w)' if re.search(r'[A-Za-zÀ-ɏ]$', term) else ''
        cleaned = re.sub(boundary + re.escape(term) + end, ' ', cleaned, flags=re.I)
    # Formula syntax is allowed; arbitrary italic prose is deliberately not exempt.
    cleaned = re.sub(r'\$\$[\s\S]*?\$\$|(?<!\$)\$[^$\n]+\$(?!\$)', ' ', cleaned)
    return cleaned

def source_language_leaks(text, allow=(), min_words=5, source_lang='en'):
    get_lang_profile(source_lang)
    cleaned = mask_allowed(text, allow)
    latin = r"[A-Za-zÀ-ɏΑ-Ͽ][A-Za-zÀ-ɏΑ-Ͽ’'\-]*"
    cyrillic = r"[Ѐ-ԯ][Ѐ-ԯ’'\-]*"
    word = cyrillic if source_lang == 'ru' else latin
    pattern = word + r'(?:[ \t,;:!?—–-]+' + word + r'){' + str(min_words - 1) + r',}'
    hits = [m.group(0).strip()[:160] for m in re.finditer(pattern, cleaned)]
    if source_lang == 'ja':
        for match in re.finditer(r'[一-龯々ぁ-ヿー]{10,}', cleaned):
            if len(re.findall(r'[ぁ-ヿ]', match.group(0))) >= 4:
                hits.append(match.group(0)[:160])
    return hits

def source_overlap_snippets(text, source, lang='en', allow=(), min_words=5):
    cleaned = mask_allowed(text, allow)
    if lang == 'ja':
        fold = lambda value: ''.join(ch for ch in value if ch.isalnum())
        original, candidate = fold(source), fold(cleaned)
        width = 18
        source_grams = {original[i:i + width] for i in range(max(0, len(original) - width + 1))}
        # Also catches kanji-heavy Japanese that a kana-only detector cannot identify.
        return list(dict.fromkeys(candidate[i:i + width] for i in range(max(0, len(candidate) - width + 1)) if candidate[i:i + width] in source_grams))[:5]
    source_words, candidate_words = source_tokens(source), source_tokens(cleaned)
    grams = {tuple(source_words[i:i + min_words]) for i in range(max(0, len(source_words) - min_words + 1))}
    return list(dict.fromkeys(' '.join(candidate_words[i:i + min_words]) for i in range(max(0, len(candidate_words) - min_words + 1)) if tuple(candidate_words[i:i + min_words]) in grams))[:5]

def chapter_pattern(lang='en'):
    profile = get_lang_profile(lang)
    stem = (r'(?P<word>[一二三四五六七八九十百千〇零\d]+)[章部編篇]' if lang == 'ja' else r'(?P<word>\d+|[IVXLCDM]+|[^\W\d_]+)\b')
    prefix = r'第\s*' if lang == 'ja' else r'(?:' + profile['chapter'] + r')\s+'
    # Decimal subsection headings (1.1) must not qualify as chapters.
    return re.compile(r'^(?P<hashes>#{1,4}\s+)?(?:\*\*)?(?P<body>(?:' + prefix + stem + r'|(?P<digit>\d{1,3})(?![\d.]\d)(?:[.:]|\s)\s*(?=[A-ZÀ-Я一-龯]))[^\n]*?)(?:\*\*)?\s*$', re.M | re.I)

def back_pattern(lang='en'):
    return re.compile(r'^(?:#{1,4}\s+)?(?:\*\*)?\s*(?:' + get_lang_profile(lang)['back'] + r')\s*(?:\*\*)?\s*$', re.M | re.I)

def chapter_number(value):
    if value.isdigit():
        return int(value)
    words = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split()
    word_maps = {'eins': 1, 'zwei': 2, 'drei': 3, 'vier': 4, 'fünf': 5, 'un': 1, 'premier': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'первая': 1, 'вторая': 2, 'третья': 3, 'первый': 1, 'второй': 2, 'третий': 3}
    if value.casefold() in word_maps:
        return word_maps[value.casefold()]
    if value.casefold() in words:
        return words.index(value.casefold())
    if re.fullmatch(r'[IVXLCDM]+', value, re.I):
        table, total, previous = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}, 0, 0
        for letter in reversed(value.upper()):
            number = table[letter]
            total += -number if number < previous else number
            previous = max(previous, number)
        return total
    digits, total, part = dict(zip('〇零一二三四五六七八九', (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9))), 0, 0
    if all(ch in digits or ch in '十百千' for ch in value):
        for ch in value:
            if ch in digits:
                part = digits[ch]
            else:
                total += (part or 1) * {'十': 10, '百': 100, '千': 1000}[ch]
                part = 0
        return total + part
    return None
