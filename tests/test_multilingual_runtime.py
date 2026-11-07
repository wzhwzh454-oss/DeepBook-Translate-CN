"""Observable multilingual, import and resume behavior of the development build."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from language import detect_source_language, count_source_units, source_language_leaks, source_overlap_snippets
from intake_book import split_into_chapters, save_ocr_artifact
from source_io import read_book_file
from source_io import OCRRequiredError
from bt_common import norm_orig, match_fold, sha256_file
from orchestrate_book import gate_current, tracked_inputs, digest
from rename_term import safe_replace_term, replaceable_matches
from workspace_config import load_config

SAMPLES = {
    'en': ('Chapter', 'The book asks whether a belief is true and whether the evidence is reliable. These are different questions because the evidence can change while the belief remains the same.'),
    'de': ('Kapitel', 'Die Frage ist, ob der Glaube wahr ist und ob die Gründe zuverlässig sind. Das sind verschiedene Fragen, weil sich die Gründe ändern können und der Glaube dennoch bestehen bleibt.'),
    'fr': ('Chapitre', 'Le livre demande si une croyance est vraie et si les raisons sont fiables. Ce sont des questions distinctes, car les raisons peuvent changer dans le temps sans que la croyance change.'),
    'es': ('Capítulo', 'El libro pregunta si una creencia es verdadera y si las razones son fiables. Estas preguntas son diferentes porque las razones pueden cambiar, pero la creencia puede ser la misma.'),
    'ru': ('Глава', 'В книге рассматривается вопрос о том, истинно ли убеждение и надёжны ли основания. Это разные вопросы, потому что основания могут изменяться, а само убеждение при этом остаётся прежним.'),
    'ja': ('第', 'この本では、ある信念が真であることと、その根拠が信頼できることを区別する。根拠が変化しても信念がそのまま維持される場合があるため、この二つの問いは同じではない。'),
}

def sample_book(code):
    heading, body = SAMPLES[code]
    title = lambda n: f'第{n}章 問い' if code == 'ja' else f'{heading} {n}: Question'
    return '\n\n'.join(f'# {title(n)}\n\n{body}' for n in (1, 2))

class MultilingualRuntime(unittest.TestCase):
    def test_six_language_intake(self):
        for code in SAMPLES:
            with self.subTest(code=code):
                text = sample_book(code)
                self.assertEqual(detect_source_language(text), code)
                chapters = split_into_chapters(text)
                self.assertEqual(len(chapters), 2)
                self.assertIn(SAMPLES[code][1], chapters[0]['content'])
                self.assertGreater(count_source_units(text, code), 20)

    def test_toc_and_subsections_do_not_create_chapters(self):
        text = 'Contents\nChapter 1 ... 3\nChapter 2 ... 8\n\n' + sample_book('en').replace('# Chapter 2', '## 1.1 A subquestion\n\nMore discussion.\n\n# Chapter 2')
        chapters = split_into_chapters(text, source_lang='en')
        self.assertEqual(len([ch for ch in chapters if ch['kind'] == 'chapter']), 2)
        self.assertIn('1.1 A subquestion', next(ch for ch in chapters if ch['kind'] == 'chapter')['content'])

    def test_non_english_term_keys_keep_final_s(self):
        self.assertNotEqual(norm_orig('sens', 'fr'), norm_orig('sen', 'fr'))
        self.assertEqual(norm_orig('consciousness'), 'consciousness')
        self.assertEqual(norm_orig('analysis'), 'analysis')

    def test_foreign_prose_and_math(self):
        for code, text in [('de', 'Die Gründe sind für diese Frage wichtig'), ('fr', 'Les raisons sont données dans le texte'), ('es', 'Las razones se explican en este libro'), ('ru', 'Эти основания имеют значение для нашего вывода'), ('ja', 'この結論はまだ確定しているわけではありません')]:
            with self.subTest(code=code):
                self.assertTrue(source_language_leaks(text, source_lang=code))
        self.assertFalse(source_language_leaks('consciousness'))
        self.assertFalse(source_language_leaks('这是 $alpha beta gamma delta epsilon zeta$ 的公式。'))
        self.assertTrue(source_language_leaks('*the reasons are relevant to this question*'))
        self.assertNotEqual(match_fold('∀x P(x)'), match_fold('∃x P(x)'))
        self.assertNotEqual(match_fold('x < y'), match_fold('x > y'))

    def test_short_preface_and_single_chapter_notes_survive(self):
        source = 'A short substantive preface.\n\n# Chapter 1: Evidence\n\nThe full discussion.\n\n# Notes\n\nA substantive explanatory note.'
        chapters = split_into_chapters(source, source_lang='en')
        self.assertEqual([c['kind'] for c in chapters], ['front', 'chapter', 'back'])
        self.assertIn('short substantive preface', chapters[0]['content'])
        self.assertIn('substantive explanatory note', chapters[2]['content'])

    def test_kanji_source_copy_is_detected(self):
        copied = '認識主体経験判断形成条件概念構造分析対象関係規定'
        self.assertTrue(source_overlap_snippets(copied, copied, 'ja'))

    def test_encoding_preserves_western_russian_and_japanese(self):
        with tempfile.TemporaryDirectory() as tmp:
            for code, codec in [('fr', 'cp1252'), ('ru', 'cp1251'), ('ja', 'shift_jis')]:
                with self.subTest(code=code):
                    path = Path(tmp) / (code + '.txt')
                    source = SAMPLES[code][1]
                    if code == 'fr':
                        source += " L'évaluation est précise."
                    path.write_bytes(source.encode(codec))
                    text, report = read_book_file(path)
                    self.assertEqual(text, source)
                    self.assertTrue(report['encoding_review'])

    def test_epub_reads_spine_instead_of_filename_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'book.epub'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>')
                archive.writestr('OPS/content.opf', '<package><metadata><title>Example</title><language>fr</language></metadata><manifest><item id="a" href="z.xhtml" media-type="application/xhtml+xml"/><item id="b" href="a.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b" linear="no"/></spine></package>')
                archive.writestr('OPS/z.xhtml', '<html><body><h1>FIRST</h1><p>First text</p><script>IGNORE</script></body></html>')
                archive.writestr('OPS/a.xhtml', '<html><body><h1>SECOND</h1><p>Second text</p></body></html>')
            text, report = read_book_file(path)
            self.assertLess(text.index('FIRST'), text.index('SECOND'))
            self.assertNotIn('IGNORE', text)
            self.assertEqual(len(report['spine']), 2)

    def test_epub_intake_smoke_from_book_file_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'book.epub'
            workspace = root / 'workspace'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>')
                archive.writestr('OPS/content.opf', '<package><metadata><title>Fixture</title></metadata><manifest><item id="first" href="z.xhtml" media-type="application/xhtml+xml"/><item id="second" href="a.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>')
                archive.writestr('OPS/z.xhtml', '<html><body><h1>Chapter 1: First</h1><p>This first chapter presents an argument and several examples for the reader to consider.</p></body></html>')
                archive.writestr('OPS/a.xhtml', '<html><body><h1>Chapter 2: Second</h1><p>This second chapter develops the argument and explains why the evidence matters.</p></body></html>')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/intake_book.py'), '--input', str(path), '--workspace', str(workspace)],
                cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                self.fail("intake output was not JSON: %r / %r" % (result.stdout, result.stderr))
            self.assertEqual(data['total_chapters'], 2)
            book = json.loads((workspace / 'book.json').read_text(encoding='utf-8'))
            self.assertEqual([chapter['title'] for chapter in book['chapters']], ['Chapter 1: First', 'Chapter 2: Second'])
            first = (workspace / book['chapters'][0]['dir'] / 'source.md').read_text(encoding='utf-8')
            second = (workspace / book['chapters'][1]['dir'] / 'source.md').read_text(encoding='utf-8')
            self.assertIn('first chapter', first)
            self.assertIn('second chapter', second)
            report = json.loads((workspace / 'input/intake-report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['input']['format'], 'epub')

    def test_image_pdf_requires_explicit_ocr_consent(self):
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / 'image-only.pdf'
            document = fitz.open()
            page = document.new_page()
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24), 0)
            pixmap.clear_with(255)
            page.insert_image(page.rect, pixmap=pixmap)
            document.save(pdf_path)
            document.close()

            with self.assertRaises(OCRRequiredError) as caught:
                read_book_file(pdf_path)
            self.assertEqual(caught.exception.pages, [1])
            self.assertFalse(caught.exception.consent_received)

            workspace = root / 'paused-workspace'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/intake_book.py'), '--input', str(pdf_path), '--workspace', str(workspace)],
                cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertTrue(result.stdout.strip(), result.stderr)
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.fail("intake output was not JSON: %r / %r" % (result.stdout, result.stderr))
            self.assertEqual(data['error_code'], 'ocr_required')
            self.assertEqual(data['pages'], [1])
            self.assertFalse((workspace / 'book.json').exists())

    def test_successful_ocr_is_saved_before_book_intake_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'workspace'
            details = {
                'format': 'pdf',
                'pages': [{'page': 1, 'characters': 0, 'ocr': False},
                          {'page': 2, 'characters': 42, 'ocr': True}],
            }
            record = save_ocr_artifact(workspace, details,
                                       ['Readable text on page one.', 'Recognized text on page two.'])
            markdown = (workspace / 'input/ocr-text.md').read_text(encoding='utf-8')
            report = json.loads((workspace / 'input/intake-report.json').read_text(encoding='utf-8'))
            self.assertEqual(record['pages'], [2])
            self.assertIn('PDF 第 1 页', markdown)
            self.assertIn('Recognized text on page two.', markdown)
            self.assertEqual(report['status'], 'ocr-complete-awaiting-book-intake')

    def test_rename_does_not_repeat_or_corrupt_other_terms(self):
        text = '运气、认识论运气与好运气都需区分。'
        result = safe_replace_term(text, '运气', '认识论运气', ['好运气'])
        self.assertEqual(result, '认识论运气、认识论运气与好运气都需区分。')
        self.assertEqual(safe_replace_term(result, '运气', '认识论运气', ['好运气']), result)
        self.assertEqual(len(replaceable_matches(text, '运气', '认识论运气', ['好运气'])), 1)

    def test_gate_uses_same_windows_newline_hash_as_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source-numbered.md'
            path.write_bytes('[P1] text\r\n'.encode('utf-8'))
            report = Path(tmp) / 'gate.json'
            report.write_text(json.dumps({'ok': True, 'meta': {'input_sha256': {str(path.resolve()): sha256_file(path)}}}), encoding='utf-8')
            self.assertTrue(gate_current(report, [path]))
            path.write_text('[P1] changed', encoding='utf-8')
            self.assertFalse(gate_current(report, [path]))

    def test_delivery_inputs_include_source_and_new_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter = root / 'chapters/ch01'
            chapter.mkdir(parents=True)
            source = chapter / 'source-numbered.md'
            source.write_text('[P1] original', encoding='utf-8')
            book = {'chapters': [{'dir': 'chapters/ch01'}]}
            self.assertIn(source, tracked_inputs(root, book))
            before = digest(source)
            source.write_text('[P1] changed', encoding='utf-8')
            self.assertNotEqual(before, digest(source))
            new = chapter / 'outline.json'
            new.write_text('{}', encoding='utf-8')
            self.assertIn(new, tracked_inputs(root, book))

    def test_config_is_discovered_from_section_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'book.json').write_text(json.dumps({'source_lang': 'ru', 'translation': {'readability': {'sentence_soft': 49}}}), encoding='utf-8')
            section = root / 'chapters/ch01/sections'
            section.mkdir(parents=True)
            config = load_config(section)
            self.assertEqual(config['translation']['readability']['sentence_soft'], 49)
            self.assertEqual(config['translation']['coverage_min_rate'], 1.0)

    def test_empty_term_plan_and_length_advisory_do_not_stop_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in [('term-plan.json', '{"terms":[]}'), ('outline.json', '{"sections":[{"k":1,"anchors":[[1,1]]}]}'), ('source-numbered.md', '[P1] This is an ordinary passage.'), ('final.md', '一个短而完整的句子。')]:
                (root / name).write_text(content, encoding='utf-8')
            for script, args in [('check_term_plan.py', ['--term-plan', root / 'term-plan.json', '--outline-json', root / 'outline.json', '--numbered', root / 'source-numbered.md']), ('check_merged.py', ['--merged', root / 'final.md', '--floor', 2000, '--ceiling', 4000])]:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *map(str, args)], capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'PYTHONUTF8': '1'})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
