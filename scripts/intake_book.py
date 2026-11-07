# -*- coding: utf-8 -*-
"""intake_book.py — 六种语言书籍材料摄入、自动分章与工作区初始化。

支持输入：
  - Markdown / TXT 文件
  - 电子版 PDF 与 EPUB（内置 PyMuPDF / HTML 读取并清洗跨页/连字符噪声）
  - 已拆分的章节文件目录（--dir 模式）

功能：
  1. 识别并提取全书章节，建立 chapters/ch01, ch02... 标准目录；
  2. 自动调用 number_source.py 为各章源文生成 [P1], [P2]... 物理段落锚点；
  3. 初始化全书元数据 book.json、全局术语台账 global-term-ledger.json、全书脉络账本 book-continuity.json；
  4. 自动生成第 1 章启动交接 Prompt (handover-to-ch01.prompt.md)。
"""
from language import detect_language_details, get_lang_profile, count_source_units, expected_zh_chars, chapter_pattern, back_pattern, chapter_number
from source_io import OCRRequiredError, read_book_file
from workspace_config import DEFAULTS
from bt_common import write_json_atomic
import argparse
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
NUMBER_SOURCE_SCRIPT = ROOT / "number_source.py"


_PREFIXES = {'self', 'non', 'anti', 'semi', 'quasi', 'post', 'pre', 'co', 'ex', 'well', 'ill', 'half',
             'all', 'cross', 'multi', 'meta', 'pro', 'counter', 'inter', 'intra', 'neo',
             'selbst', 'nicht', 'vor', 'nach', 'über', 'unter', 'zwischen', 'gegen'}


def dehyphenate(text):
    """Join words broken by a line-end hyphen WITHOUT destroying real compounds.

    v2.0 joined every `x-\\ny` ("self-\\nevident" -> "selfevident", "non-\\nideal" -> "nonideal") and could
    even cross blank lines. Decision order: capitalised continuation keeps the hyphen (post-\\nGettier);
    the document's own vocabulary decides (unhyphenated form seen elsewhere -> join, hyphenated form seen
    elsewhere -> keep); otherwise well-known compound prefixes keep it; otherwise join.
    """
    from collections import Counter
    word_pat = r"[^\W\d_]{2,}(?:-[^\W\d_]{2,})*"
    vocabulary = Counter(w.casefold() for w in re.findall(word_pat, text, flags=re.UNICODE))

    def repl(match):
        left, right = match.group(1), match.group(2)
        if right[0].isupper():
            return left + '-' + right
        joined, hyphenated = (left + right).casefold(), (left + '-' + right).casefold()
        if vocabulary.get(joined, 0):
            return left + right
        if vocabulary.get(hyphenated, 0) or left.casefold() in _PREFIXES:
            return left + '-' + right
        return left + right

    return re.sub(r'(\b[^\W\d_]{2,})-[ \t]*\n[ \t]*([^\W\d_]{2,}\b)', repl, text, flags=re.UNICODE)


def strip_running_headers(text, min_repeats=4):
    """Drop short lines that repeat on many pages (running heads/feet, page counters with digits masked)."""
    from collections import Counter

    def key(line):
        return re.sub(r'\d+', '#', line.strip().lower())

    lines = text.split('\n')
    counts = Counter(key(l) for l in lines
                     if l.strip() and len(l.strip()) <= 80 and not l.lstrip().startswith(('#', '-', '*', '>', '|', '[P')))
    noisy = {k for k, c in counts.items() if c >= min_repeats and len(k) >= 4 and not re.search(r'[.!?:;]$', k)}
    kept = [l for l in lines if not (l.strip() and key(l) in noisy)]
    return '\n'.join(kept), sorted(noisy)


def clean_book_text(text: str, strip_headers: bool = False, report: dict = None, source_lang='en') -> str:
    """针对长篇书籍进行噪声清洗、跨行连字符修复与段落标准化。"""
    text = text.lstrip('\ufeff')
    if source_lang in ('en', 'de', 'fr', 'es', 'ru'):
        text = dehyphenate(text)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    if strip_headers:
        text, removed = strip_running_headers(text)
        if report is not None:
            report['removed_running_headers'] = removed

    noise_patterns = [
        re.compile(r'^\s*\d{1,4}\s*$'),  # standalone page number (digit-only lines: review in intake-report)
        re.compile(r'^\s*Page\s+\d+\s+(?:of\s+\d+)?\s*$', re.IGNORECASE),
        re.compile(r'^\s*©\s*\d{4}.*$', re.IGNORECASE),
    ]
    cleaned_lines, dropped_digits = [], 0
    for line in text.split("\n"):
        if any(pat.match(line.strip()) for pat in noise_patterns):
            dropped_digits += 1
            continue
        cleaned_lines.append(line)
    if report is not None:
        report['dropped_page_number_lines'] = dropped_digits

    final_paragraphs = []
    for block in re.split(r'\n\s*\n', "\n".join(cleaned_lines)):
        b = block.strip()
        if not b:
            continue
        if b.startswith(('#', '- ', '* ', '>', '|')):
            final_paragraphs.append(b)
        else:
            final_paragraphs.append(('' if source_lang == 'ja' else ' ').join(line.strip() for line in b.splitlines()))
    return "\n\n".join(final_paragraphs) + "\n"


def extract_from_pdf(pdf_path: Path) -> str:
    """从 PDF 抽取纯文本，优先使用 fitz，失败自动回退到 markitdown。"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        text_chunks = []
        for page in doc:
            text_chunks.append(page.get_text())
        extracted = "\n\n".join(text_chunks)
        if extracted.strip():
            return extracted
    except Exception as e:
        print(f"Warning: PyMuPDF 提取失败 ({e})，尝试使用 markitdown 备用方案...", file=sys.stderr)

    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        result = mid.convert(str(pdf_path))
        return result.text_content
    except Exception as e:
        raise RuntimeError(f"PDF 提取失败，请确保安装了 pymupdf 或 markitdown: {e}")


_NUMBER_WORDS = {w: i for i, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split())}
_BACK_RE = re.compile(r'^(?:#{1,3}\s+)?(?:\*\*)?\s*(?:Notes|Endnotes|Bibliography|References|Works Cited|Index|Acknowledg(?:e)?ments|About the Authors?|Glossary)\s*(?:\*\*)?\s*$', re.I | re.M)
_CAND_RE = re.compile(r'^(?P<hashes>#{1,3}\s+)?(?:\*\*)?(?P<body>(?:(?:Chapter|CHAPTER|Part|PART)\s+(?P<word>\d+|[IVXLCDM]+|[A-Za-z]+)\b|(?P<digit>\d{1,2})(?![\d.]\d)(?:[.:]|\s)\s*(?=[A-Z\u4e00-\u9fff]))[^\n]*?)(?:\*\*)?\s*$', re.M)


def _roman(value):
    table, total, prev = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}, 0, 0
    for ch in reversed(value.upper()):
        n = table[ch]
        total += -n if n < prev else n
        prev = max(prev, n)
    return total


def _candidate_number(match):
    word, digit = match.group('word'), match.group('digit')
    if digit:
        return int(digit)
    if word.isdigit():
        return int(word)
    if re.fullmatch(r'[IVXLCDM]+', word, re.I) and word.upper() == word:
        return _roman(word)
    return _NUMBER_WORDS.get(word.lower())


def _longest_increasing(items):
    """items: [(position, number)] -> longest strictly increasing-by-number subsequence (O(n^2), n small)."""
    best = [[it] for it in items]
    for i in range(len(items)):
        for j in range(i):
            if items[j][1] < items[i][1] and len(best[j]) + 1 > len(best[i]):
                best[i] = best[j] + [items[i]]
    return max(best, key=len) if best else []


def split_into_chapters(full_text: str, return_back_matter: bool = False, source_lang='auto'):
    """Chapter detection that does not mistake sub-sections, TOC lines or back matter for chapters.

    v2.0 treated every `## 1.1 ...`, `## Mill on Liberty`, `## Civil Society` as a chapter and left the
    bibliography inside the last chapter. v2.1: candidates are grouped by (heading level, kind); the group
    with the longest strictly-increasing chapter-number sequence wins; repeated numbers (a TOC) keep the
    occurrence with the longest body; `1.1`-style numbers never qualify; back matter is split off.
    """
    language = detect_language_details(full_text)['language'] if source_lang == 'auto' else source_lang
    groups = {}
    for m in chapter_pattern(language).finditer(full_text):
        number = chapter_number(m.group('word') or m.group('digit'))
        if re.search(r'\.{3,}|…{2,}|\s\d+\s*$', m.group('body')) and not m.group('hashes'):
            continue
        if number is None or re.match(r'^(?:#{1,3}\s+)?\d+\.\d', m.group(0).strip()):
            continue
        kind = 'word' if m.group('word') else 'digit'
        groups.setdefault((len((m.group('hashes') or '').strip()), kind), []).append((m.start(), number, m))
    best, best_key = [], None
    for key, found in groups.items():
        found.sort(key=lambda t: t[0])
        spans = {}
        for idx, (pos, number, _) in enumerate(found):
            end = found[idx + 1][0] if idx + 1 < len(found) else len(full_text)
            if number not in spans or end - pos > spans[number][1] - spans[number][0]:
                spans[number] = (pos, end, idx)
        chosen = sorted(spans.values())
        run = _longest_increasing([(found[i][0], found[i][1]) for _, _, i in chosen])
        if len(run) > len(best) or (len(run) == len(best) and best_key and key[0] < best_key[0]):
            best, best_key = run, key
    if not best:  # fallback: top-level '# ' headings
        tops = [(m.start(), 0, m) for m in re.finditer(r'^#\s+(?P<body>[^\n]+)\s*$', full_text, re.M)]
        best = [(p, n) for p, n, _ in tops]
        best_key = (1, 'top')
    chapters, back = [], ''
    if best:
        starts = [p for p, _ in best]
        line_end = lambda p: full_text.find('\n', p) if full_text.find('\n', p) >= 0 else len(full_text)
        titles = [re.sub(r'^#+\s*|\*+', '', full_text[p:line_end(p)]).strip() for p in starts]
        preface = full_text[:starts[0]].strip()
        preface_lines = [line.strip() for line in preface.splitlines() if line.strip()]
        only_navigation = preface_lines and all(re.fullmatch(r'#{0,4}\s*(?:Contents|Table of Contents|Inhalt|Table des matières|Índice|Содержание|目次)', line, re.I) or re.search(r'(?:\.{3,}|…{2,})\s*\d+\s*$', line) for line in preface_lines)
        if preface and not only_navigation:
            chapters.append({'title': 'Preface & Front Matter (序言、致谢与全书体例)', 'content': preface, 'kind': 'front'})
        for i, p in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(full_text)
            body = full_text[p:end].strip()
            if i == len(starts) - 1:
                cut = next((b for b in back_pattern(language).finditer(body) if b.start() > 0), None)
                if cut:
                    body, back = body[:cut.start()].strip(), body[cut.start():].strip()
            chapters.append({'title': titles[i] or 'Chapter %d' % (i + 1), 'content': body, 'kind': 'chapter'})
    else:
        chapters.append({'title': '全文', 'content': full_text.strip(), 'kind': 'chapter'})
    # Back matter is a production task too: notes/references must not disappear from delivery.
    if back and not return_back_matter:
        chapters.append({'title': '注释、参考文献与附录', 'content': back, 'kind': 'back'})
    return (chapters, back) if return_back_matter else chapters


def save_ocr_artifact(workspace: Path, input_details: dict, page_texts):
    """Persist the scanned text before later chapter parsing can fail."""
    ocr_pages = [page for page in input_details.get("pages", []) if page.get("ocr")]
    if not ocr_pages or not page_texts:
        return None
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    ocr_md_path = input_dir / "ocr-text.md"
    blocks = []
    for index, text in enumerate(page_texts, 1):
        body = (text or "").strip() or "〔本页未提取到文字〕"
        blocks.append(f"## PDF 第 {index} 页\n\n{body}")
    ocr_md_path.write_text("# OCR 文字版\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    record = {
        "markdown": "input/ocr-text.md",
        "engine": "PyMuPDF OCR (Tesseract)",
        "pages": [page["page"] for page in ocr_pages],
        "total_pages": len(page_texts),
        "status": "completed; sampled pages still require human/model review",
    }
    write_json_atomic(input_dir / "intake-report.json", {
        "status": "ocr-complete-awaiting-book-intake",
        "input": {key: value for key, value in input_details.items() if key != "page_texts"},
        "ocr": record,
    })
    return record


def main():
    parser = argparse.ArgumentParser(description="英语、德语、法语、西班牙语、俄语或日语书籍摄入与工作区初始化（PDF / EPUB / MD / TXT）")
    parser.add_argument("--input", "-i", type=str, help="输入书籍文件路径（PDF / EPUB / MD / TXT）")
    parser.add_argument("--dir", "-d", type=str, help="输入已拆分的章节目录路径（可选）")
    parser.add_argument("--workspace", "-w", type=str, required=True, help="全书工作区目标绝对路径")
    parser.add_argument("--title", "-t", type=str, default="", help="书名（中文或英文）")
    parser.add_argument("--author", "-a", type=str, default="", help="作者名")
    parser.add_argument("--slug", "-s", type=str, default="", help="书籍短标识 (英文小写连字符)")
    parser.add_argument("--lang", choices=("auto", "en", "de", "fr", "es", "ru", "ja"), default="auto")
    parser.add_argument("--encoding", help="Agent 确认的文本编码；默认自动识别，不需要用户设置")
    parser.add_argument("--allow-ocr", action="store_true", help="仅在用户明确同意后，允许对图片 PDF 调用当前环境已有的 OCR")
    parser.add_argument("--plan-only", action="store_true", help="只打印检测到的章节表（标题/词数），不写任何文件；先人工确认再正式摄入")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的 book.json（会重置进度并重写源文，慎用）")
    args = parser.parse_args()
    selected_lang = args.lang

    workspace = Path(args.workspace).resolve()
    if (workspace / "book.json").exists() and not args.force and not args.plan_only:
        print(json.dumps({"ok": False, "error": "工作区已存在 book.json；重新摄入会重写 source-numbered.md 并使已有 points/outline 的 [Pn] 失效。确需重来请加 --force"}, ensure_ascii=False))
        sys.exit(1)
    if not args.plan_only:
        workspace.mkdir(parents=True, exist_ok=True)
    chapters_dir = workspace / "chapters"
    raw_dir = workspace / "raw"
    if not args.plan_only:
        chapters_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
    intake_report = {}
    back_matter = ""

    book_title = args.title
    book_author = args.author
    book_slug = args.slug

    raw_chapters = []
    input_details = {}
    ocr_page_texts = None
    ocr_record = None

    if args.dir:
        input_dir = Path(args.dir).resolve()
        files = sorted(list(input_dir.glob("*.md")) + list(input_dir.glob("*.txt")),
                       key=lambda p: ([int(x) for x in re.findall(r'\d+', p.stem)] or [10**9], p.name))
        if not files:
            print(json.dumps({"ok": False, "error": f"目录 {input_dir} 下未找到 .md 或 .txt 文件"}, ensure_ascii=False))
            sys.exit(1)
        for f in files:
            content = f.read_text(encoding="utf-8-sig")
            clean_title = re.sub(r'^\d+[\s\-_.]*', '', f.stem).strip()
            kind = "chapter"
            stem_lower = f.stem.lower()
            if any(k in stem_lower for k in ("preface", "front")):
                kind = "front"
            elif any(k in stem_lower for k in ("back", "reference", "index", "appendix")):
                kind = "back"
            raw_chapters.append({
                "title": clean_title or f.stem,
                "content": content,
                "kind": kind
            })
            if not args.plan_only:
                shutil.copy2(f, raw_dir / f.name)
        input_details = {"format": "dir", "files": len(files)}
        intake_report["input"] = input_details
        if not book_title:
            book_title = input_dir.name
    elif args.input:
        input_path = Path(args.input).resolve()
        if not input_path.exists():
            print(json.dumps({"ok": False, "error": f"输入文件不存在: {input_path}"}, ensure_ascii=False))
            sys.exit(1)

        if not args.plan_only:
            shutil.copy2(input_path, raw_dir / input_path.name)
        if not book_title:
            book_title = input_path.stem

        try:
            raw_text, input_details = read_book_file(input_path, args.lang, args.encoding, allow_ocr=args.allow_ocr)
        except OCRRequiredError as error:
            error_code = "ocr_required" if not args.allow_ocr else "ocr_unavailable"
            message = (
                "PDF 含有无法直接读取的图片页；请先向用户说明并征得同意，再使用 --allow-ocr 重试。"
                if not args.allow_ocr else
                "已获得 OCR 同意，但当前 OCR 工具或语言数据不可用；请寻找并配置可用方案后再重试。"
            )
            print(json.dumps({
                "ok": False,
                "error_code": error_code,
                "error": message,
                "pages": error.pages,
                "details": error.details,
            }, ensure_ascii=False))
            return 1
        ocr_page_texts = input_details.pop("page_texts", None)
        intake_report["input"] = input_details
        if not args.plan_only:
            ocr_record = save_ocr_artifact(workspace, input_details, ocr_page_texts)
            if ocr_record:
                intake_report["ocr"] = ocr_record
        metadata = input_details.get("metadata", {})
        book_title = args.title or metadata.get("title") or book_title
        book_author = args.author or metadata.get("creator") or book_author

        detected = detect_language_details(raw_text)
        selected_lang = detected["language"] if args.lang == "auto" else args.lang
        intake_report["language_detection"] = detected
        cleaned_text = clean_book_text(raw_text, report=intake_report, source_lang=selected_lang)
        raw_chapters, back_matter = split_into_chapters(cleaned_text, return_back_matter=True, source_lang=selected_lang)
        if back_matter:
            raw_chapters.append({"title": "注释、参考文献与附录", "content": back_matter, "kind": "back"})
    else:
        print(json.dumps({"ok": False, "error": "必须提供 --input 或 --dir 参数"}, ensure_ascii=False))
        sys.exit(1)

    if args.dir:
        detected = detect_language_details("\n\n".join(ch["content"] for ch in raw_chapters))
        selected_lang = detected["language"] if args.lang == "auto" else args.lang
        intake_report["language_detection"] = detected
        for chapter in raw_chapters:
            chapter["content"] = clean_book_text(chapter["content"], source_lang=selected_lang)
    if not raw_chapters or not any(ch["content"].strip() for ch in raw_chapters):
        raise ValueError("book has no readable content")
    get_lang_profile(selected_lang)
    if not book_slug:
        book_slug = re.sub(r'[^a-zA-Z0-9_\-]+', '-', book_title).strip('-').lower() or "book"

    if args.plan_only:
        table = [{"id": i, "title": c["title"], "kind": c.get("kind", "chapter"),
                  "words": count_source_units(c["content"], selected_lang)} for i, c in enumerate(raw_chapters, 1)]
        print(json.dumps({"ok": True, "plan_only": True, "source_lang": selected_lang, "chapters": table, "back_matter_chars": len(back_matter), **intake_report}, ensure_ascii=False, indent=2))
        return 0

    # 初始化章节结构
    book_metadata_chapters = []
    import subprocess
    if back_matter:
        (raw_dir / "back-matter.md").write_text(back_matter, encoding="utf-8")
    from bt_common import sha256_text

    for idx, ch in enumerate(raw_chapters, start=1):
        ch_dir_name = f"ch{idx:02d}"
        ch_dir = chapters_dir / ch_dir_name
        ch_dir.mkdir(parents=True, exist_ok=True)
        sections_dir = ch_dir / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)

        source_path = ch_dir / "source.md"
        source_numbered_path = ch_dir / "source-numbered.md"

        source_path.write_text(ch["content"], encoding="utf-8")

        # 运行 number_source.py 为该章源文打上 [P1], [P2] 编号
        cmd = [
            sys.executable, str(NUMBER_SOURCE_SCRIPT),
            "--source", str(source_path),
            "--out", str(source_numbered_path)
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        if res.returncode != 0 or not source_numbered_path.exists():
            print(json.dumps({"ok": False, "error": f"章节 {ch_dir_name} 编号失败: {res.stdout.strip()} {res.stderr.strip()}"}, ensure_ascii=False))
            sys.exit(1)

        # 估算字数（含带音标的拉丁字母，如 Gödel）
        words = count_source_units(ch["content"], selected_lang)

        book_metadata_chapters.append({
            "id": idx,
            "dir": f"chapters/{ch_dir_name}",
            "title": ch["title"],
            "words": words, "source_units": words, "source_lang": selected_lang,
            "source_unit": get_lang_profile(selected_lang)["unit"], "expected_zh_chars": expected_zh_chars(words, selected_lang),
            "kind": ch.get("kind", "chapter"),
            "source_sha256": sha256_text(ch["content"]),
            "status": "pending"
        })

    # 创建全书元数据 book.json
    book_info = {
        "slug": book_slug, "source_lang": selected_lang,
        "translation": DEFAULTS["translation"], "layout": DEFAULTS["layout"],
        "style_profile": DEFAULTS["book"]["style_profile"],
        "title": book_title,
        "author": book_author or "未知作者",
        "total_chapters": len(book_metadata_chapters),
        "current_chapter": 1,
        "created_at": "",
        "chapters": book_metadata_chapters
    }
    write_json_atomic(workspace / "book.json", book_info)
    (workspace / "input").mkdir(exist_ok=True)
    write_json_atomic(workspace / "input" / "intake-report.json", {**intake_report, "back_matter_chars": len(back_matter)})

    # 创建全局术语台账 global-term-ledger.json
    term_ledger_file = workspace / "global-term-ledger.json"
    if not term_ledger_file.exists():
        term_ledger_file.write_text("[]\n", encoding="utf-8")

    # 创建全书脉络账本 book-continuity.json
    continuity_file = workspace / "book-continuity.json"
    if not continuity_file.exists():
        continuity_data = {
            "book_thesis": f"《{book_title}》核心学术要旨与核心问题（待在第1章或全书规划中具体提炼）",
            "book_arc": "全书论证弧线：从问题提出，逐步辨析概念，展开各章专门论证，最终得出结论。",
            "chapter_summaries": []
        }
        continuity_file.write_text(json.dumps(continuity_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 生成第 1 章启动交接 Prompt
    ch01_dir = chapters_dir / "ch01"
    template_path = ROOT.parent / "prompts" / "P9-handover-template.md"
    template = template_path.read_text(encoding="utf-8")

    # 确定内置 Python 解释器路径
    venv_py = ROOT.parent / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    python_bin = str(venv_py) if venv_py.exists() else sys.executable

    replacements = {
        "{{SOURCE_LANG}}": selected_lang,
        "{{BOOK_TITLE}}": book_title,
        "{{BOOK_AUTHOR}}": book_author or "未知作者",
        "{{SKILL_DIR}}": str(ROOT.parent),
        "{{PYTHON}}": str(python_bin),
        "{{WORKSPACE}}": str(workspace),
        "{{NEXT_CHAPTER_NUM}}": "1",
        "{{NEXT_CHAPTER_TITLE}}": book_metadata_chapters[0]["title"],
        "{{CHAPTER_DIR}}": str(ch01_dir),
        "{{BOOK_THESIS}}": f"《{book_title}》全书论证探索",
        "{{TOTAL_CHAPTERS}}": str(len(book_metadata_chapters)),
        "{{COMPLETED_CHAPTERS}}": "0",
        "{{PREVIOUS_CHAPTERS_SUMMARY}}": "无（第一章为全书起点）",
        "{{CURRENT_CHAPTER_NUM}}": "0",
        "{{CURRENT_CHAPTER_THESIS}}": "无（全书首章）",
        "{{CURRENT_CHAPTER_ENDING_TAIL}}": "无（全书开篇）",
        "{{PENDING_QUESTIONS}}": "1. 明确全书核心问题与基本预设；\n2. 引入核心概念体系与第一章论证目标。",
        "{{GLOBAL_TERM_TABLE}}": "暂无已固化术语（本章将定义第一批核心基础术语）",
    }

    ch01_prompt = template
    for k, v in replacements.items():
        ch01_prompt = ch01_prompt.replace(k, v)

    ch01_prompt_path = ch01_dir / "handover-to-ch01.prompt.md"
    ch01_prompt_path.write_text(ch01_prompt, encoding="utf-8")

    result = {
        "ok": True,
        "workspace": str(workspace),
        "book_title": book_title,
        "total_chapters": len(book_metadata_chapters),
        "chapters": book_metadata_chapters,
        "ch01_prompt_path": str(ch01_prompt_path)
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

