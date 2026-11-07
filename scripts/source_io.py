"""Book input readers; EPUB follows its declared spine and PDF keeps page structure."""
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from language import FUNCTION_WORDS, source_tokens
import posixpath
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile

class BookHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        if tag in ('p', 'div', 'section', 'article', 'blockquote', 'ul', 'ol'):
            self.parts.append('\n\n')
        elif re.fullmatch(r'h[1-6]', tag):
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag == 'br':
            self.parts.append('\n')
        elif tag == 'tr':
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' | ')
        elif tag == 'img':
            info = dict(attrs)
            self.parts.append('\n[图示：' + (info.get('alt') or info.get('src') or '无文字说明') + ']\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in ('p', 'div', 'section', 'article', 'blockquote', 'table', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
    def text(self):
        return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', ''.join(self.parts)).strip()


class OCRRequiredError(ValueError):
    def __init__(self, pages, consent_received=False, details=None):
        self.pages = pages
        self.consent_received = consent_received
        self.details = details or []
        super().__init__('PDF image pages require OCR on pages: ' + ', '.join(map(str, pages)))

def read_epub(path):
    with zipfile.ZipFile(path) as book:
        container = ET.fromstring(book.read('META-INF/container.xml'))
        rootfile = next((node.get('full-path') for node in container.iter() if node.tag.rsplit('}', 1)[-1] == 'rootfile'), None)
        if not rootfile:
            raise ValueError('EPUB container has no package document')
        package = ET.fromstring(book.read(rootfile))
        base = posixpath.dirname(rootfile)
        metadata, manifest = {}, {}
        for node in package.iter():
            local = node.tag.rsplit('}', 1)[-1]
            if local in ('title', 'creator', 'language') and node.text:
                metadata.setdefault(local, node.text.strip())
            if local == 'item':
                manifest[node.get('id')] = node.attrib
        chunks, spine = [], []
        for node in package.iter():
            if node.tag.rsplit('}', 1)[-1] != 'itemref':
                continue
            item = manifest.get(node.get('idref'))
            if not item or 'xhtml' not in item.get('media-type', '') and 'html' not in item.get('media-type', ''):
                continue
            member = posixpath.normpath(posixpath.join(base, unquote(item['href'].split('#')[0])))
            parser = BookHTML()
            raw = book.read(member)
            # XHTML normally declares UTF-8; respect an explicit XML encoding when present.
            declaration = re.search(br'encoding=[\x22\x27]([^\x22\x27]+)', raw[:200])
            encoding = declaration.group(1).decode('ascii') if declaration else 'utf-8-sig'
            parser.feed(raw.decode(encoding))
            body = parser.text()
            if body:
                chunks.append(body)
                spine.append({'member': member, 'linear': node.get('linear', 'yes'), 'characters': len(body)})
        if not chunks:
            raise ValueError('EPUB contains no readable spine text; it may be encrypted or image-only')
        return '\n\n'.join(chunks), {'format': 'epub', 'metadata': metadata, 'spine': spine}

def read_text_file(path, lang='auto', encoding=None):
    raw = Path(path).read_bytes()
    if encoding:
        return raw.decode(encoding), {'format': Path(path).suffix.lstrip('.'), 'encoding': encoding, 'encoding_review': False}
    for codec in (('utf-16',) if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig',)):
        try:
            return raw.decode(codec), {'format': Path(path).suffix.lstrip('.'), 'encoding': codec, 'encoding_review': False}
        except (UnicodeError, LookupError):
            continue
    # Score legacy decodings by actual language evidence, not the first codec
    # which accepts every byte. The Agent reviews low-confidence input itself.
    candidates = []
    hints = {**FUNCTION_WORDS, 'ru': 'и в не на что это как по для из но с к или', 'ja': 'の は が を に と で です ます する ある ない'}
    for codec, languages in (('cp1252', ('en', 'de', 'fr', 'es')), ('cp1251', ('ru',)), ('shift_jis', ('ja',)), ('euc_jp', ('ja',))):
        if lang != 'auto' and lang not in languages:
            continue
        try:
            decoded = raw.decode(codec)
        except UnicodeError:
            continue
        if any(ord(ch) < 32 and ch not in '\n\r\t' for ch in decoded):
            continue
        tokens = source_tokens(decoded)
        score = max(sum(tokens.count(w) for w in hints[code].split()) for code in languages)
        if 'ja' in languages:
            score += len(re.findall(r'[ぁ-ゖ]', decoded)) / 6
        candidates.append((score, codec, decoded))
    if not candidates:
        raise ValueError('cannot decode text input without data loss; Agent should identify encoding and retry --encoding')
    score, codec, decoded = max(candidates, key=lambda item: item[0])
    return decoded, {'format': Path(path).suffix.lstrip('.'), 'encoding': codec, 'encoding_review': True, 'encoding_evidence': score}

def read_pdf(path, lang='auto', allow_ocr=False):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    chunks, pages, issues = [], [], []
    with fitz.open(str(path)) as document:
        if document.is_encrypted:
            raise ValueError('PDF is encrypted and cannot be read')
        for index, page in enumerate(document):
            text = page.get_text('text', sort=True)
            used_ocr = False
            if len(text.strip()) < 25 and page.get_images():
                if not allow_ocr:
                    issues.append({'page': index + 1, 'issue': 'user consent required before OCR'})
                    chunks.append(text)
                    pages.append({'page': index + 1, 'characters': len(text.strip()), 'ocr': False})
                    continue
                eff_lang = lang
                if eff_lang == 'auto' and ''.join(chunks).strip():
                    from language import detect_source_language
                    eff_lang = detect_source_language(''.join(chunks))
                code = {'en': 'eng', 'de': 'deu', 'fr': 'fra', 'es': 'spa', 'ru': 'rus', 'ja': 'jpn'}.get(eff_lang, 'eng')
                try:
                    text = page.get_text(textpage=page.get_textpage_ocr(language=code, full=True))
                    used_ocr = True
                except Exception as error:
                    issues.append({'page': index + 1, 'issue': 'OCR tool or language data unavailable', 'detail': str(error)[:200]})
            chunks.append(text)
            pages.append({'page': index + 1, 'characters': len(text.strip()), 'ocr': used_ocr})
    if issues:
        raise OCRRequiredError(
            [item['page'] for item in issues],
            consent_received=allow_ocr,
            details=issues[:20],
        )
    if not ''.join(chunks).strip():
        raise ValueError('PDF has no readable text')
    return '\n\n'.join(chunks), {'format': 'pdf', 'pages': pages, 'page_texts': chunks}

def read_book_file(path, lang='auto', encoding=None, allow_ocr=False):
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix == '.epub':
        return read_epub(path)
    if suffix == '.pdf':
        return read_pdf(path, lang, allow_ocr=allow_ocr)
    if suffix in ('.md', '.txt', '.markdown'):
        return read_text_file(path, lang, encoding)
    raise ValueError('unsupported book format: ' + suffix)
