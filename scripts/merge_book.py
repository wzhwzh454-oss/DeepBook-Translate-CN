# -*- coding: utf-8 -*-
"""merge_book.py — 全书汇编与交付质检 (v2.1).

v2.0 -> v2.1 (each item reproduced in the review):
  * integrity gate is FAIL-CLOSED by default (--allow-violations restores the old behaviour)
  * 'coverage' defence re-runs check_coverage on the real points/final/audit triple instead of
    grepping for a "[FAIL]" marker that no real audit ever contains
  * alias handling is the SAME policy as chapter stage (check_terms.term_variant_report): alias_ban is
    advisory unless --strict-aliases, user_banned (incl. term-plan top level and book.json) is hard,
    canonical names containing an alias are exempt (no more '运气' vs '认识论运气' false positives)
  * a chapter without chapter-final.md is a violation — never "the first section stands in for it" and
    assembly no longer writes chapter-final.md as a side effect
  * term dependency graph: namespaced uids, Kahn layering, Tarjan cycles, forward references, Mermaid
  * DOCX: real Heading styles, TOC field, PAGE field, A4, Latin/CJK font split, distinct 〔补充〕 style
"""
import argparse
import json
import re
import sys
from pathlib import Path
from workspace_config import load_config
from terminology import render_core_table
from language import expected_zh_chars

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import textutil  # noqa: E402
from bt_common import (StateError, analyze_term_graph, norm_orig, read_json_strict,  # noqa: E402
                       resolve_chapter_final, term_graph_mermaid, write_json_atomic, write_text_atomic)

PLACEHOLDERS = (r'（第\s*\d+\s*章暂未完成定稿）', r'<!--\s*TODO', r'【待定稿】', r'\[待补充\]', r'\{\{NEXT_CHAPTER',
                r'\{\{BOOK_TITLE\}', r'【第\d+节】', r'〔待核〕')


def natural_sort_key(path_or_str):
    name = path_or_str.name if hasattr(path_or_str, 'name') else str(path_or_str)
    nums = re.findall(r'\d+', name)
    return int(nums[0]) if nums else 0


def chapter_titles(chapters):
    """Display titles: front matter unnumbered, real chapters numbered 1..N, no 'Chapter 3: Chapter 3 ...'."""
    out, number = [], 0
    for ch in chapters:
        raw = ch.get('title_zh') or ch.get('title', '')
        stripped = re.sub(r'^(?:chapter|part|section)\s+(?:\d+|[ivxlcdm]+|[a-z]+)\s*[:.\-—–]?\s*', '', raw, flags=re.I)
        stripped = re.sub(r'^\d+\s*[.:]?\s+', '', stripped).strip() or raw
        if ch.get('kind') in ('front', 'back'):
            out.append({**ch, 'heading': stripped})
        else:
            number += 1
            out.append({**ch, 'heading': '第 %d 章  %s' % (number, stripped), 'number': number})
    return out


# ------------------------------------------------------------------ markdown outputs
def build_book_markdown(book_data, chapters_content, continuity_data):
    title, author = book_data.get('title', '未命名书籍'), book_data.get('author', '未知作者')
    lines = ['# 《%s》' % title, '**作者**：%s' % author, '**研读改写**：AI 学术研读助手（book-translator）', '',
             '---', '', '## 全书研读导读与论证脉络', continuity_data.get('book_arc') or '（尚未填写全书论证脉络）', '', '## 全书目录', '']
    chapters = chapter_titles(chapters_content)
    for ch in chapters:
        lines.append('- [%s](#chapter-%s)' % (ch['heading'], ch['id']))
    lines.extend(['', '---', ''])
    for ch in chapters:
        lines.append('<a id="chapter-%s"></a>' % ch['id'])
        lines.append('# ' + ch['heading'])
        lines.append('')
        # demote headings inside chapters so a chapter's own '# ' never competes with the chapter title
        lines.append(re.sub(r'^(#{1,5})\s', lambda m: '#' + m.group(1) + ' ', ch['content'].strip(), flags=re.M))
        lines.extend(['', '---', ''])
    return '\n'.join(lines)


def build_term_ledger_markdown(book_data, global_terms):
    title = book_data.get('title', '未命名书籍')
    analysis = analyze_term_graph(global_terms)
    nodes = analysis['nodes']
    name = {uid: t.get('zh', uid) for uid, t in nodes.items()}
    uid_of = {id(t): uid for uid, t in nodes.items()}
    lines = ['# 《%s》全书术语与概念台账' % title, '',
             '> 已锁定 (locked) 的术语在后续章节具有约束力；alias_ban 为模型提出的候选别名（需语境复核），user_banned 才是硬性禁令。', '',
             '## 一、术语总览', '',
             '| uid | 中文译名 | 原词 | 首次确立 | 锁定状态 | 概念依赖 (depends_on) | 核心界定 | 候选别名 (alias_ban) |', '| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |']
    for t in global_terms:
        deps = '、'.join(name.get(d, d) for d in analysis['edges'].get(uid_of.get(id(t)), [])) or '无'
        lines.append('| %s | %s | %s | 第 %s 章 | %s | %s | %s | %s |' % (
            uid_of.get(id(t), ''), t.get('zh', ''), t.get('orig', ''), t.get('defined_in_chapter', 1),
            '已锁定 (locked)' if t.get('locked', True) else '未锁定', deps, t.get('gloss') or '无', '、'.join(t.get('alias_ban', [])) or '无'))
    lines.extend(['', '## 二、概念依赖拓扑（Kahn 分层 / Tarjan 环路检测）', ''])
    if not global_terms:
        lines.append('暂无已固化术语。')
        return '\n'.join(lines) + '\n'
    for depth, layer in enumerate(analysis['layers']):
        label = '第 0 层：不依赖其他概念' if depth == 0 else '第 %d 层：依赖前面各层' % depth
        lines.append('- **%s**：%s' % (label, '、'.join(name[u] for u in layer)))
    for cycle in analysis['cycles']:
        lines.append('- **环路（须修正）**：' + ' ⇄ '.join(name[u] for u in cycle))
    for ref in analysis['forward_refs']:
        lines.append('- **前向依赖（须修正）**：%s 依赖于更晚章节才引入的 %s' % (name[ref['term']], name[ref['depends_on']]))
    for ref in analysis['unresolved']:
        lines.append('- 未解析依赖：%s → %s' % (name[ref['term']], ref['depends_on']))
    lines.extend(['', '```mermaid', term_graph_mermaid(analysis), '```'])
    return '\n'.join(lines) + '\n'


def build_reader_glossary(book_data, terms):
    lines = ['# 《%s》核心术语表' % book_data.get('title', ''), '', render_core_table(terms)]
    for term in terms:
        if term.get('translation_note'):
            lines.extend(['', '**%s译注**：%s' % (term.get('zh', ''), term['translation_note'])])
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------ integrity gate
def _section_coverage_problems(ch_dir, sec, k):
    from check_coverage import check_coverage
    from check_points import parse_points
    base = ch_dir / 'sections'
    audit, points, final = base / ('coverage-%s.md' % k), base / ('%s-points.md' % k), base / ('%s-final.md' % k)
    if not audit.exists():
        return ['缺少覆盖核验反查报告 (coverage-%s.md)' % k]
    if not (points.exists() and final.exists()):
        return ['无法核验覆盖：缺少 %s-points.md 或 %s-final.md' % (k, k)]
    parsed, errors = parse_points(points.read_text(encoding='utf-8'))
    result = check_coverage(final.read_text(encoding='utf-8'), parsed, audit.read_text(encoding='utf-8'), min_rate=load_config(ch_dir)['translation'].get('coverage_min_rate', 1.0))
    problems = ['覆盖核验未通过：%s' % v for v in (errors + result['violations'])[:4]]
    if re.search(r'\[FAIL\]|\bFAILED\b|未通过|覆盖率未达标', audit.read_text(encoding='utf-8')):
        problems.append('反查报告含显式失败标记')
    return problems


def check_book_delivery_integrity(workspace: Path, book_data: dict, global_terms: list, strict_aliases=False):
    from check_terms import term_variant_report
    from check_punctuation_budget import check_files as check_punctuation_budget
    from p6_review import review_state
    violations, advisories = [], []
    chapter_summary, term_drift_summary, audit_summary = [], [], []
    chapters = book_data.get('chapters', [])
    if not chapters:
        violations.append('book.json 中未定义任何章节信息 (chapters 列表为空)')
    texts, plans = {}, []

    # 1. completeness -------------------------------------------------------------
    for ch in chapters:
        ch_id, ch_dir = ch.get('id'), workspace / ch.get('dir', 'chapters/ch%02d' % ch.get('id', 0))
        res = {'id': ch_id, 'title': ch.get('title', ''), 'status': 'ok', 'cjk_count': 0, 'issues': []}

        def flag(status, message):
            res['status'] = status if res['status'] == 'ok' else res['status']
            res['issues'].append(message)
            violations.append(message)

        if not ch_dir.exists():
            flag('missing_directory', '第 %s 章目录不存在: %s' % (ch_id, ch_dir))
            chapter_summary.append(res)
            continue
        final, problems = resolve_chapter_final(ch_dir)
        if final is None:
            flag('missing_final', '第 %s 章缺少定稿文本 (chapter-final.md)；分节定稿不能代替整章定稿' % ch_id)
            chapter_summary.append(res)
            continue
        for problem in problems:
            flag('ambiguous_final', '第 %s 章: %s' % (ch_id, problem))
        content = final.read_text(encoding='utf-8')
        texts[ch_id] = content
        res['cjk_count'] = textutil.cjk_count(content)
        p6 = review_state(ch_dir, final)
        res['manual_p6'] = p6.get('status')
        if not p6.get('ok'):
            for problem in p6.get('violations', []):
                flag('p6_review', '第 %s 章 P6 冷读：%s' % (ch_id, problem))
        punctuation = check_punctuation_budget(ch_dir / 'source-numbered.md', final)
        res['punctuation_counts'] = {
            'source': punctuation.get('source', {}).get('counts'),
            'translation': punctuation.get('translation', {}).get('counts'),
        }
        if not punctuation.get('ok'):
            for problem in punctuation.get('violations', []):
                flag('punctuation_budget', '第 %s 章标点上限：%s' % (ch_id, problem))
        if not content.strip():
            flag('empty', '第 %s 章定稿文本为空 (0 字符)' % ch_id)
        elif res['cjk_count'] < 80 and ch.get('kind') not in ('front', 'back'):
            flag('too_short', '第 %s 章定稿正文篇幅异常过短（仅 %d 字），疑似未完成定稿' % (ch_id, res['cjk_count']))
        if ch.get('status') not in (None, 'done'):
            flag('not_done', '第 %s 章在 book.json 中状态为 %r（未经交接固化）' % (ch_id, ch.get('status')))
        words = ch.get('source_units') or ch.get('words') or 0
        if words and ch.get('kind') not in ('front', 'back'):
            ratio = res['cjk_count'] / expected_zh_chars(words, book_data.get('source_lang', 'en'))
            if ratio < 0.4:
                flag('too_short', '第 %s 章忠实层字数比仅 %.2f（<0.40），疑似大段缺失' % (ch_id, ratio))
            elif ratio < 0.75:
                advisories.append('第 %s 章字数比 %.2f 低于 0.75 参考线，请回看关键定义与论证步骤' % (ch_id, ratio))
        for pat in PLACEHOLDERS:
            m = re.search(pat, content)
            if m:
                flag('placeholder', "第 %s 章定稿正文中残留未完成占位符: '%s'" % (ch_id, m.group(0)))
        chapter_summary.append(res)

    # 2. terminology --------------------------------------------------------------
    by_orig, by_zh, banned_top = {}, {}, set(book_data.get('user_banned', []))
    combined = {'terms': [], 'user_banned': []}
    for ch in chapters:
        ch_id = ch.get('id')
        path = workspace / ch.get('dir', 'chapters/ch%02d' % ch_id) / 'term-plan.json'
        if not path.exists():
            continue
        try:
            plan = read_json_strict(path)
        except StateError as exc:
            violations.append('第 %s 章 term-plan 不可读: %s' % (ch_id, exc))
            continue
        plans.append(plan)
        combined['user_banned'].extend(plan.get('user_banned', []))
        for t in plan.get('terms', []):
            combined['terms'].append(t)
            key = norm_orig(t.get('orig'), t.get('source_lang', book_data.get('source_lang', 'en')))
            if key:
                by_orig.setdefault(key, []).append({'zh': t.get('zh', '').strip(), 'orig': t.get('orig'), 'chapter': 'ch%02d' % ch_id, 'sense': t.get('collision')})
            if t.get('zh'):
                by_zh.setdefault(t['zh'].strip(), []).append({'orig': key, 'chapter': 'ch%02d' % ch_id, 'sense': t.get('collision')})
    for t in global_terms:
        combined['terms'].append(t)
        key = norm_orig(t.get('orig'), t.get('source_lang', book_data.get('source_lang', 'en')))
        if key:
            by_orig.setdefault(key, []).append({'zh': t.get('zh', '').strip(), 'orig': t.get('orig'), 'chapter': 'ledger(ch%s)' % t.get('defined_in_chapter'), 'sense': t.get('collision')})
        if t.get('zh'):
            by_zh.setdefault(t['zh'].strip(), []).append({'orig': key, 'chapter': 'ledger', 'sense': t.get('collision')})
    combined['user_banned'].extend(banned_top)
    for key, entries in by_orig.items():
        zhs = {e['zh'] for e in entries if e['zh']}
        if len(zhs) > 1:
            detail = '; '.join('[%s]->%s' % (e['chapter'], e['zh']) for e in entries)
            message = "跨章术语漂移: 原词 '%s' 存在多个译名: %s" % (entries[0]['orig'], detail)
            (advisories if any(e['sense'] for e in entries) else violations).append(message)
            term_drift_summary.append({'orig': entries[0]['orig'], 'issue': 'drift', 'detail': detail})
    for zh, entries in by_zh.items():
        if len({e['orig'] for e in entries if e['orig']}) > 1:
            advisories.append("术语译名歧义提醒: 中文译名 '%s' 对应多个不同原词" % zh)
    for ch_id, text in texts.items():
        report = term_variant_report(text, combined)
        violations.extend('第 %s 章: %s' % (ch_id, issue) for issue in report['violations'])
        for issue in report['advisories']:
            (violations if strict_aliases else advisories).append('第 %s 章: %s' % (ch_id, issue))
        for match in report['matches']:
            term_drift_summary.append({'chapter': ch_id, 'banned_word': match['alias'], 'line': match['line'], 'hard': match['hard']})
    graph = analyze_term_graph(global_terms)
    for cycle in graph['cycles']:
        violations.append('概念依赖存在环路: ' + ' -> '.join(cycle))
    for ref in graph['forward_refs']:
        violations.append('概念前向依赖: %(term)s 依赖更晚章节引入的 %(depends_on)s' % ref)
    for ref in graph['unresolved']:
        advisories.append('概念依赖无法解析: %(term)s -> %(depends_on)s' % ref)

    # 3. coverage -----------------------------------------------------------------
    for ch in chapters:
        ch_id = ch.get('id')
        ch_dir = workspace / ch.get('dir', 'chapters/ch%02d' % ch_id)
        audit = {'chapter': ch_id, 'sections_checked': 0, 'missing_coverage': [], 'failed_coverage': []}
        outline_file = ch_dir / 'outline.json'
        if not outline_file.exists():
            if ch_dir.exists():
                violations.append('第 %s 章缺少 outline.json，无法验证分节覆盖' % ch_id)
            audit_summary.append(audit)
            continue
        try:
            outline = read_json_strict(outline_file)
        except StateError as exc:
            violations.append('第 %s 章 outline.json 不可读: %s' % (ch_id, exc))
            audit_summary.append(audit)
            continue
        for sec in outline.get('sections', []):
            k = sec.get('k', 1)
            audit['sections_checked'] += 1
            for problem in _section_coverage_problems(ch_dir, sec, k):
                violations.append('第 %s 章第 %s 节%s' % (ch_id, k, problem))
                (audit['missing_coverage'] if '缺少' in problem else audit['failed_coverage']).append(k)
        numbered = ch_dir / 'source-numbered.md'
        if numbered.exists():
            total = len(re.findall(r'^\[P\d+\]', numbered.read_text(encoding='utf-8'), flags=re.M))
            covered = {n for sec in outline.get('sections', []) for a, b in sec.get('anchors', []) for n in range(a, b + 1)}
            declared = set()
            for entry in outline.get('excluded', []):
                for first, last in re.findall(r'P(\d+)(?:\s*[\-–—]\s*P?(\d+))?', str(entry)):
                    declared.update(range(int(first), int(last or first) + 1))
            gap = sorted(set(range(1, total + 1)) - covered - declared)
            if gap:
                advisories.append('第 %s 章有 %d 个源段落未被任何小节锚定: %s' % (ch_id, len(gap), ', '.join('P%d' % n for n in gap[:12])))
        audit_summary.append(audit)

    return {'ok': not violations, 'violations': violations, 'advisories': advisories,
            'total_chapters_checked': len(chapters), 'chapter_summary': chapter_summary,
            'term_drift_summary': term_drift_summary, 'audit_summary': audit_summary,
            'policy': {'strict_aliases': strict_aliases}}


# ------------------------------------------------------------------ DOCX
def _style_fonts(style, east='宋体', latin='Times New Roman', size=None, bold=None, color=None):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn('w:rFonts'))
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        rpr.insert(0, fonts)
    for attr in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
        if fonts.get(qn(attr)) is not None:
            del fonts.attrib[qn(attr)]
    fonts.set(qn('w:ascii'), latin)
    fonts.set(qn('w:hAnsi'), latin)
    fonts.set(qn('w:cs'), latin)
    fonts.set(qn('w:eastAsia'), east)
    if size:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    style.font.color.rgb = color if color is not None else RGBColor(0, 0, 0)


def _add_field(paragraph, instruction, placeholder=''):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def mark(kind):
        run = paragraph.add_run()
        element = OxmlElement('w:fldChar')
        element.set(qn('w:fldCharType'), kind)
        run._r.append(element)

    mark('begin')
    run = paragraph.add_run()
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = ' %s ' % instruction
    run._r.append(instr)
    mark('separate')
    paragraph.add_run(placeholder)
    mark('end')


def _add_inline(paragraph, text):
    for token in re.split(r'(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)', text):
        if not token:
            continue
        if token.startswith('**') and token.endswith('**') and len(token) > 4:
            paragraph.add_run(token[2:-2]).bold = True
        elif token.startswith('*') and token.endswith('*') and len(token) > 2:
            paragraph.add_run(token[1:-1]).italic = True
        else:
            paragraph.add_run(token)


def _add_table(doc, rows, widths_cm=None, font_pt=9, header=True):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = 'Table Grid'
    table.autofit = False
    if widths_cm is None and len(rows[0]) == 3:
        widths_cm = [2.5, 3.2, 8.9]
    if widths_cm:
        for column, width in zip(table.columns, widths_cm):
            column.width = Cm(width)
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            cell = table.rows[r].cells[c]
            if widths_cm:
                cell.width = Cm(widths_cm[c])
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(4)
            paragraph.paragraph_format.line_spacing = Pt(14)
            indentation = paragraph._p.get_or_add_pPr().get_or_add_ind()
            indentation.set(qn('w:firstLineChars'), '0')
            run = paragraph.add_run(str(value))
            run.font.size = Pt(font_pt)
            run.bold = bool(header and r == 0)
        if header and r == 0:  # repeat header row on every page
            flag = OxmlElement('w:tblHeader')
            flag.set(qn('w:val'), 'true')
            table.rows[0]._tr.get_or_add_trPr().append(flag)
    return table


def add_markdown_block(doc, block):
    """Markdown block -> real Word styles (headings demoted one level, quote, lists, tables, supplement)."""
    text = block.strip()
    if not text:
        return
    lines = text.splitlines()
    heading = re.match(r'^(#{1,6})\s+(.*)$', lines[0])
    if heading and len(lines) == 1:
        doc.add_paragraph(heading.group(2), style='Heading %d' % min(len(heading.group(1)) + 1, 4))
    elif all(l.lstrip().startswith('|') for l in lines):
        rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines if not re.match(r'^\s*\|?\s*:?-{2,}', l)]
        if rows and len({len(r) for r in rows}) == 1:
            _add_table(doc, rows)
        else:
            doc.add_paragraph(text)
    elif all(l.lstrip().startswith('>') for l in lines):
        _add_inline(doc.add_paragraph(style='Quote'), ' '.join(re.sub(r'^\s*>\s?', '', l) for l in lines))
    elif all(re.match(r'^\s*[-*]\s+', l) for l in lines):
        for l in lines:
            _add_inline(doc.add_paragraph(style='List Bullet'), re.sub(r'^\s*[-*]\s+', '', l))
    elif all(re.match(r'^\s*\d+[.)]\s+', l) for l in lines):
        for l in lines:
            _add_inline(doc.add_paragraph(style='List Number'), re.sub(r'^\s*\d+[.)]\s+', '', l))
    else:
        _add_inline(doc.add_paragraph(style='Supplement' if text.startswith('〔补充〕') else 'Normal'),
                    ' '.join(l.strip() for l in lines))


def build_book_docx(book_data, chapters_content, global_terms, output_docx_path: Path):
    try:
        import docx
        from docx.enum.section import WD_SECTION
        from docx.enum.style import WD_STYLE_TYPE
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt, RGBColor
    except ImportError:
        print('Warning: 未安装 python-docx，跳过生成 DOCX 文件', file=sys.stderr)
        return False

    title = book_data.get('title', '')
    doc = docx.Document()
    core = doc.core_properties
    core.title, core.author, core.subject = '《%s》中文研读稿' % title, book_data.get('author', ''), '中文研读改写稿'
    core.language = 'zh-CN'

    # document defaults: East-Asian language so Word applies Chinese line-breaking/punctuation rules
    defaults = doc.styles.element.find(qn('w:docDefaults'))
    if defaults is not None and defaults.find(qn('w:rPrDefault')) is not None:
        rpr = defaults.find(qn('w:rPrDefault')).find(qn('w:rPr'))
        lang = rpr.find(qn('w:lang')) if rpr is not None else None
        if rpr is not None and lang is None:
            lang = OxmlElement('w:lang')
            rpr.append(lang)
        if lang is not None:
            lang.set(qn('w:val'), 'en-US')
            lang.set(qn('w:eastAsia'), 'zh-CN')

    styles = doc.styles
    normal = styles['Normal']
    _style_fonts(normal, size=12)
    normal.paragraph_format.line_spacing = Pt(22)
    normal.paragraph_format.first_line_indent = Pt(24)
    normal.paragraph_format.space_after = Pt(6)
    contextual = normal.element.get_or_add_pPr().find(qn('w:contextualSpacing'))
    if contextual is not None:
        normal.element.get_or_add_pPr().remove(contextual)
    ind = normal.element.get_or_add_pPr().find(qn('w:ind'))
    if ind is not None:
        ind.set(qn('w:firstLineChars'), '200')  # two characters at any font size
    for name, size, before, after in (('Heading 1', 18, 0, 18), ('Heading 2', 15, 18, 8), ('Heading 3', 13, 12, 6), ('Heading 4', 12, 10, 4)):
        style = styles[name]
        _style_fonts(style, east='黑体', size=size, bold=True)
        style.paragraph_format.first_line_indent = Pt(0)
        style.paragraph_format.space_before, style.paragraph_format.space_after = Pt(before), Pt(after)
        style.paragraph_format.keep_with_next = True
    styles['Heading 1'].paragraph_format.page_break_before = True
    styles['Heading 1'].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    quote = styles['Quote']
    _style_fonts(quote, east='楷体', size=10.5, bold=False)
    quote.font.italic = False
    quote.paragraph_format.left_indent = quote.paragraph_format.right_indent = Cm(0.8)
    quote.paragraph_format.first_line_indent = Pt(0)
    for name in ('List Bullet', 'List Number'):
        _style_fonts(styles[name], size=12)
        styles[name].paragraph_format.first_line_indent = Pt(0)
    supplement = styles.add_style('Supplement', WD_STYLE_TYPE.PARAGRAPH)  # 〔补充〕层必须与忠实层在视觉上分开
    supplement.base_style = normal
    ppr = supplement.element.get_or_add_pPr()
    border, left = OxmlElement('w:pBdr'), OxmlElement('w:left')
    for key, value in (('val', 'single'), ('sz', '12'), ('space', '8'), ('color', '999999')):
        left.set(qn('w:' + key), value)
    border.append(left)
    ppr.append(border)
    shade = OxmlElement('w:shd')
    for key, value in (('val', 'clear'), ('color', 'auto'), ('fill', 'F3F3F3')):
        shade.set(qn('w:' + key), value)
    ppr.append(shade)
    _style_fonts(supplement, east='楷体', size=10.5)
    supplement.paragraph_format.left_indent = Cm(0.74)
    supplement.paragraph_format.first_line_indent = Pt(0)
    supplement.paragraph_format.line_spacing = Pt(20)
    for name in ('Title', 'Subtitle'):
        _style_fonts(styles[name], east='黑体', size=26 if name == 'Title' else 14, bold=name == 'Title')
        ppr = styles[name].element.get_or_add_pPr()
        for border in list(ppr.findall(qn('w:pBdr'))):
            ppr.remove(border)
        styles[name].font.italic = False
        styles[name].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        styles[name].paragraph_format.first_line_indent = Pt(0)
    toc_title = styles.add_style('TocTitle', WD_STYLE_TYPE.PARAGRAPH)
    toc_title.base_style = normal
    _style_fonts(toc_title, east='黑体', size=18, bold=True)
    toc_title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    toc_title.paragraph_format.first_line_indent = Pt(0)
    toc_title.paragraph_format.space_after = Pt(18)

    def page_setup(section):  # A4 — python-docx's template is US Letter
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2.54)
        section.left_margin = section.right_margin = Cm(3.17)

    page_setup(doc.sections[0])
    cover = doc.add_paragraph(style='Title')
    cover.paragraph_format.space_before = Pt(160)
    cover.add_run('《%s》' % title)
    doc.add_paragraph('中文研读改写本', style='Subtitle')
    doc.add_paragraph('原著：%s' % book_data.get('author', '未知作者'), style='Subtitle')

    toc_heading = doc.add_paragraph('目　录', style='TocTitle')
    toc_heading.paragraph_format.page_break_before = True
    toc = doc.add_paragraph()
    toc.paragraph_format.first_line_indent = Pt(0)
    _add_field(toc, 'TOC \\o "1-2" \\h \\z \\u', '目录')
    settings = doc.settings.element
    update = OxmlElement('w:updateFields')
    update.set(qn('w:val'), 'true')
    compat = settings.find(qn('w:compat'))
    (compat.addprevious(update) if compat is not None else settings.append(update))

    body = doc.add_section(WD_SECTION.NEW_PAGE)
    page_setup(body)
    body.header.is_linked_to_previous = False
    body.footer.is_linked_to_previous = False
    head = body.header.paragraphs[0]
    head.text = '《%s》中文研读稿' % title
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    head.paragraph_format.first_line_indent = Pt(0)
    for run in head.runs:
        run.font.size, run.font.color.rgb = Pt(9), RGBColor(128, 128, 128)
    foot = body.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    foot.paragraph_format.first_line_indent = Pt(0)
    _add_field(foot, 'PAGE', '1')
    numbering = OxmlElement('w:pgNumType')
    numbering.set(qn('w:start'), '1')
    cols = body._sectPr.find(qn('w:cols'))
    (cols.addprevious(numbering) if cols is not None else body._sectPr.append(numbering))

    for chapter in chapter_titles(chapters_content):
        doc.add_paragraph(chapter['heading'], style='Heading 1')
        for block in re.split(r'\n\s*\n', chapter['content'].strip()):
            add_markdown_block(doc, block)

    if global_terms:
        doc.add_paragraph('附录　核心术语表', style='Heading 1')
        analysis = analyze_term_graph(global_terms)
        name = {uid: t.get('zh', uid) for uid, t in analysis['nodes'].items()}
        uid_of = {id(t): uid for uid, t in analysis['nodes'].items()}
        rows = [['中文译名', '原词', '简明解释', '相关概念']]
        for t in global_terms:
            deps = '、'.join(name.get(d, d) for d in analysis['edges'].get(uid_of.get(id(t)), [])) or '无'
            rows.append([t.get('zh', ''), t.get('orig', ''), t.get('gloss') or '无', deps])
        _add_table(doc, rows, widths_cm=[2.5, 3.0, 6.6, 2.5])

    tmp = Path(str(output_docx_path) + '.tmp')
    doc.save(str(tmp))
    tmp.replace(output_docx_path)
    return True


# ------------------------------------------------------------------ main
def main(argv=None):
    parser = argparse.ArgumentParser(description='全书章节汇编、术语台账与交付质检')
    parser.add_argument('--workspace', '-w', required=True, help='全书工作区路径')
    parser.add_argument('--check', action='store_true', help='仅执行交付质检，不汇编')
    parser.add_argument('--strict', action='store_true', help='（兼容旧参数）默认已是严格模式')
    parser.add_argument('--allow-violations', action='store_true', help='质检失败仍汇编（仅供人工审阅草稿，退出码 0 且 ok=false）')
    parser.add_argument('--strict-aliases', action='store_true', help='把 alias_ban 命中也视为违规（默认仅 user_banned 为硬禁令）')
    parser.add_argument('--out-docx')
    parser.add_argument('--out-md')
    parser.add_argument('--out-glossary')
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    try:
        book_data = read_json_strict(workspace / 'book.json', required=True)
        continuity = read_json_strict(workspace / 'book-continuity.json', default={})
        global_terms = read_json_strict(workspace / 'global-term-ledger.json', default=[])
    except StateError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1
    if isinstance(global_terms, dict):
        global_terms = global_terms.get('terms', [])

    output_dir = workspace / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = book_data.get('slug', 'book')
    integrity = check_book_delivery_integrity(workspace, book_data, global_terms, args.strict_aliases)
    report_path = output_dir / ('%s-全书质检报告.json' % slug)
    write_json_atomic(report_path, integrity, backup=False)

    if args.check:
        print(json.dumps({'ok': integrity['ok'], 'report_path': str(report_path), 'violation_count': len(integrity['violations']),
                          'advisory_count': len(integrity['advisories']), 'violations': integrity['violations'],
                          'advisories': integrity['advisories']}, ensure_ascii=False, indent=2))
        return 0 if integrity['ok'] else 1
    if not integrity['ok'] and not args.allow_violations:
        print('[ERROR] 全书交付质检未通过（%d 项违规），已拒绝汇编；详见 %s' % (len(integrity['violations']), report_path), file=sys.stderr)
        for v in integrity['violations'][:20]:
            print('  ✗ ' + v, file=sys.stderr)
        return 1

    chapters_content = []
    for ch in book_data.get('chapters', []):
        ch_dir = workspace / ch.get('dir', 'chapters/ch%02d' % ch['id'])
        final, _ = resolve_chapter_final(ch_dir)
        content = final.read_text(encoding='utf-8') if final else '（第 %s 章暂未完成定稿）' % ch['id']
        summary = read_json_strict(ch_dir / 'chapter-summary.json', default={})
        plan = read_json_strict(ch_dir / 'term-plan.json', default={})
        config = load_config(workspace)
        profile = config['book'].get('style_profile', {})
        genre = profile.get('genre_family', 'humanities_scholarly') if isinstance(profile, dict) else 'humanities_scholarly'
        table_allowed = genre not in ('narrative_nonfiction', 'literary_fiction')
        table = render_core_table(plan.get('terms', [])) if config['layout'].get('include_chapter_vernacular_table') and table_allowed else ''
        if table:
            content = '## 本章核心概念\n\n' + table + '\n\n' + content
        chapters_content.append({**ch, 'title_zh': summary.get('title_zh') or ch.get('title_zh'), 'content': content})

    out_md = Path(args.out_md).resolve() if args.out_md else output_dir / ('%s-全文研读稿.md' % slug)
    out_docx = Path(args.out_docx).resolve() if args.out_docx else output_dir / ('%s-全文研读稿.docx' % slug)
    out_gloss = Path(args.out_glossary).resolve() if args.out_glossary else output_dir / ('%s-全书术语与概念台账.md' % slug)
    write_text_atomic(out_md, build_book_markdown(book_data, chapters_content, continuity))
    write_text_atomic(out_gloss, build_term_ledger_markdown(book_data, global_terms))
    reader_gloss = output_dir / ('%s-核心术语表.md' % slug)
    write_text_atomic(reader_gloss, build_reader_glossary(book_data, global_terms))
    docx_ok = build_book_docx(book_data, chapters_content, global_terms, out_docx)
    print(json.dumps({'ok': integrity['ok'] and docx_ok, 'book_title': book_data.get('title', ''), 'total_chapters': len(chapters_content),
                      'markdown_path': str(out_md), 'docx_path': str(out_docx) if docx_ok else None, 'glossary_path': str(reader_gloss), 'ledger_path': str(out_gloss),
                      'integrity_report_path': str(report_path), 'integrity_ok': integrity['ok'],
                      'violations_count': len(integrity['violations']), 'advisories_count': len(integrity['advisories'])},
                     ensure_ascii=False, indent=2))
    return 0 if docx_ok else 1


if __name__ == '__main__':
    sys.exit(main())
