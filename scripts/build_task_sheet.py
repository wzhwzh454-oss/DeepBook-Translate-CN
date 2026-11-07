# -*- coding: utf-8 -*-
"""build_task_sheet.py — 构建章节研读改写任务单（抽取/写作）。

支持模式：
  --mode extract: 生成 P3 抽取任务单（输入源文、术语计划，提取十二字段 points 与讲解单元）
  --mode write:   生成 P3 写作任务单（输入承重清单、讲解单元、前节结尾、术语表，输出纯正文）

增强特性：
  - 支持 --continuity-json / --prev-chapter-tail：跨章节承接首尾衔接
  - 支持 --global-terms：自动合入全书全局术语库
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import textutil
from bt_common import english_leaks
from language import source_language_leaks, source_overlap_snippets
from workspace_config import source_language
from check_points import parse_points
from task_json import dumps_records

LABELS = [
    '本节任务',
    '本节位置',
    '本节子问题',
    '本节核心内容',
    '本节应到达的结论',
    '本节承担的链段',
    '禁写清单',
    '全文核心问题',
    '已定术语表',
    '承接的遗留问题',
    '本节应留下的问题',
    '上一节结尾',
    '下一节子问题',
    '源材料',
    '字数要求',
]


def load_numbered(path):
    with io.open(path, encoding='utf-8') as f:
        text = f.read()
    paras = {}
    for m in re.finditer(r'^\[P(\d+)\]\s*(.*?)(?=^\[P\d+\]|\Z)', text, flags=re.M | re.S):
        paras[int(m.group(1))] = m.group(2).strip()
    return paras


def excerpt(paras, anchors):
    chunks = []
    for a, b in anchors:
        for i in range(a, b + 1):
            if i in paras:
                chunks.append(paras[i])
    return '\n\n'.join(chunks)


def prev_tail(sections_dir, k, default_tail="无（首节）"):
    if k <= 1:
        return default_tail
    path = Path(sections_dir) / f"{k - 1}-final.md"
    if not path.exists():
        # 兼容 draft 模式
        path = Path(sections_dir) / f"{k - 1}-revision.md"
    if not path.exists():
        return default_tail
    text = path.read_text(encoding='utf-8')
    blocks = textutil.split_paragraphs(text)
    return blocks[-1] if blocks else default_tail


def format_scoped_ledger(ledger, scope_text, with_gloss=False, include_all_below=60):
    """小台账全量注入（防漂移），大台账按本节上下文相关性过滤。"""
    scope = (scope_text or '').casefold()
    everything = len(ledger) <= include_all_below
    lines = []
    for term in ledger:
        orig = str(term.get('orig') or '').strip()
        zh = str(term.get('zh') or '').strip()
        if not everything and not ((zh and zh.casefold() in scope) or
                                   (orig and orig.casefold() in scope)):
            continue
        mark = f"（{orig}）" if orig else ''
        explanation = f"：{term['gloss']}" if with_gloss and term.get('gloss') else ''
        lines.append(f"{zh}{mark}{explanation}")
    return '；'.join(lines) if lines else '无'


def fill(template, values):
    out_lines = []
    lines = template.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^【([^】]+)】(.*)$', line)
        if m and m.group(1) in values:
            label = m.group(1)
            value = values[label]
            rest = m.group(2)
            if rest.endswith('：') or rest.endswith(':'):
                out_lines.append(f"【{label}】{rest}")
                out_lines.append(value)
            else:
                out_lines.append(f"【{label}】{value}")
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith('【') or nxt.strip() == '':
                    break
                i += 1
            continue
        out_lines.append(line)
        i += 1
    return '\n'.join(out_lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--k', type=int, required=True, help="本章内的子节序号")
    ap.add_argument('--outline-json', required=True, help="本章大纲 outline.json")
    ap.add_argument('--numbered', help="本章编号源文 source-numbered.md")
    ap.add_argument('--state', help="可选 state.json 或 config.json")
    ap.add_argument('--sections-dir', required=True, help="本章 sections 目录")
    ap.add_argument('--template', required=True, help="任务单模板")
    ap.add_argument('--out', required=True, help="输出任务单绝对路径")
    ap.add_argument('--profile', choices=('legacy', 'v2'), default='v2')
    ap.add_argument('--mode', choices=('extract', 'write'), default='extract')
    ap.add_argument('--points', help="承重清单路径 (write 模式必需)")
    ap.add_argument('--term-plan', help="术语计划路径")
    ap.add_argument('--teaching-units', help="讲解单元 json 路径")
    ap.add_argument('--global-terms', help="全书全局术语表 global-term-ledger.json")
    ap.add_argument('--prev-chapter-tail', help="上一章结尾段（用于第1节衔接）")
    ap.add_argument('--leak-source', help="编号源文路径：写作单中出现 5 词以上源文连续片段即判泄漏")
    args = ap.parse_args(argv)

    # v2.1: auto-discover workspace artefacts so the documented (short) command is already complete.
    sections_path = Path(args.sections_dir).resolve()
    chapter_dir = sections_path.parent
    source_lang = source_language(chapter_dir)
    if chapter_dir.parent.name == 'chapters':
        workspace_root = chapter_dir.parent.parent
        if not args.term_plan and (chapter_dir / 'term-plan.json').exists():
            args.term_plan = str(chapter_dir / 'term-plan.json')
        if not args.global_terms and (workspace_root / 'global-term-ledger.json').exists():
            args.global_terms = str(workspace_root / 'global-term-ledger.json')
        if not args.prev_chapter_tail and args.k == 1:
            m = re.fullmatch(r'ch(\d+)', chapter_dir.name)
            cont = workspace_root / 'book-continuity.json'
            if m and cont.exists():
                for s in json.loads(cont.read_text(encoding='utf-8')).get('chapter_summaries', []):
                    if s.get('chapter') == int(m.group(1)) - 1 and s.get('ending_tail'):
                        args.prev_chapter_tail = s['ending_tail']
    if not args.teaching_units and (sections_path / f"{args.k}-teaching-units.json").exists():
        args.teaching_units = str(sections_path / f"{args.k}-teaching-units.json")

    violations = []
    with io.open(args.outline_json, encoding='utf-8') as f:
        outline = json.load(f)

    state = {}
    if args.state and Path(args.state).exists():
        with io.open(args.state, encoding='utf-8') as f:
            state = json.load(f)

    # 合并全局术语与本地术语
    all_terms = list(state.get('term_ledger', []))
    if args.global_terms and Path(args.global_terms).exists():
        try:
            g_terms = json.loads(Path(args.global_terms).read_text(encoding='utf-8'))
            if isinstance(g_terms, dict):
                g_terms = g_terms.get('terms', [])
            existing_zh = {t.get('zh') for t in all_terms}
            for gt in g_terms:
                if gt.get('zh') not in existing_zh:
                    all_terms.append(gt)
        except Exception as e:
            violations.append(f"读取全局术语库出错: {e}")

    with io.open(args.template, encoding='utf-8') as f:
        template = f.read()

    # 物理隔绝防翻译腔：write 模式下任务单模板若误包含【源材料】占位符，抛错阻断
    if args.mode == 'write' and '【源材料】' in template:
        violations.append('write template contains source-material field')

    n = outline.get('total_sections', len(outline.get('sections', [])))
    sec = next((s for s in outline.get('sections', []) if s['k'] == args.k), None)
    if sec is None:
        violations.append(f"section {args.k} not found in outline.json")

    writing = args.profile == 'v2' and args.mode == 'write'
    if writing and not args.points:
        ap.error('--points is required for v2 write mode')
    if not writing and not args.numbered:
        ap.error('--numbered is required for extraction mode')

    paras = {} if writing else load_numbered(args.numbered)

    # 跨章节/跨节结尾衔接处理
    default_first_tail = args.prev_chapter_tail or "无（首节开篇）"
    tail = prev_tail(args.sections_dir, args.k, default_tail=default_first_tail) if writing else ''

    material = excerpt(paras, sec['anchors']) if (sec and not writing) else ''
    if sec and not material and not writing:
        violations.append(f"anchor excerpt empty for section {args.k}")
    if args.profile == 'v2' and not writing and sec:
        material = '\n\n'.join(f"[P{number}] {paras.get(number, '')}" for start, stop in sec['anchors'] for number in range(start, stop + 1) if number in paras)

    writer_points = ''
    if writing:
        points, errors = parse_points(Path(args.points).read_text(encoding='utf-8'))
        violations.extend(errors)
        writer_points = '\n'.join('｜'.join(point.get(field, '未登记') for field in ('id', 'kind', 'holder', 'statement', 'qualifiers', 'bearing', 'hint', 'force', 'argument', 'terms')) for point in points)
        if args.teaching_units and Path(args.teaching_units).exists():
            from reader_v3 import validate_teaching_units
            units = json.loads(Path(args.teaching_units).read_text(encoding='utf-8')).get('units', [])
            violations.extend(validate_teaching_units(units, points))
            point_map = {point['id']: point for point in points}
            cards = []
            for unit in units:
                material_points = [{key: point_map[point_id].get(key, '') for key in ('id', 'kind', 'holder', 'statement', 'qualifiers', 'force', 'terms', 'hint')} for point_id in unit.get('point_ids', []) if point_id in point_map]
                cards.append({**unit, 'source_material': material_points})
            writer_points = dumps_records(cards)

    if args.k == 1 and args.k == n:
        position = '首节（兼末节：既要提出问题，也要收束到论证实际支持的强度）'
    elif args.k == 1:
        position = '首节'
    elif args.k == n:
        position = '末节'
    else:
        position = f"中间节（第{args.k}节，共{n}节）"

    next_sub = '无'
    if args.k < n:
        nxt = next((s for s in outline.get('sections', []) if s['k'] == args.k + 1), None)
        if nxt:
            next_sub = nxt.get('sub_question', '无')

    # 读取并合入 term-plan 中的 user_banned 到禁写清单
    plan_user_banned = []
    term_plan = None
    if args.term_plan and Path(args.term_plan).exists():
        try:
            with io.open(args.term_plan, encoding='utf-8') as f:
                term_plan = json.load(f)
            if isinstance(term_plan, dict):
                top_banned = term_plan.get('user_banned', [])
                if isinstance(top_banned, list):
                    for b in top_banned:
                        if isinstance(b, str) and b.strip() and b.strip() not in plan_user_banned:
                            plan_user_banned.append(b.strip())
                for t in term_plan.get('terms', []):
                    if isinstance(t, dict):
                        t_banned = t.get('user_banned', [])
                        if isinstance(t_banned, list):
                            for b in t_banned:
                                if isinstance(b, str) and b.strip() and b.strip() not in plan_user_banned:
                                    plan_user_banned.append(b.strip())
        except Exception as e:
            violations.append(f"读取术语计划出错: {e}")

    prohibited_items = []
    if sec and sec.get('prohibited'):
        raw_p = sec['prohibited']
        if isinstance(raw_p, list):
            for item in raw_p:
                if isinstance(item, str) and item.strip() and item.strip() not in prohibited_items:
                    prohibited_items.append(item.strip())
        elif isinstance(raw_p, str):
            for item in raw_p.splitlines():
                if item.strip() and item.strip() not in prohibited_items:
                    prohibited_items.append(item.strip())

    for item in plan_user_banned:
        if item not in prohibited_items:
            prohibited_items.append(item)

    prohibited_text = '\n'.join(prohibited_items) if prohibited_items else '无'

    inherits = sec.get('inherits', '无') if sec else '无'
    open_question = sec.get('open_question', '无') if sec else '无'
    scope_text = '\n'.join([
        material,
        writer_points,
        tail,
        sec.get('sub_question', '') if sec else '',
        sec.get('core_content', '') if sec else '',
        sec.get('conclusion', '') if sec else '',
        sec.get('chain_role', '') if sec else '',
        prohibited_text,
        inherits,
        open_question,
        next_sub,
    ])

    ledger_text = format_scoped_ledger(all_terms, scope_text, with_gloss=args.profile == 'v2')

    planned_terms = ''
    if term_plan is not None:
        from check_term_plan import check_term_plan
        validation = check_term_plan(term_plan, outline, locked_terms=all_terms)
        violations.extend(validation.get('violations', []))
        if validation.get('ok'):
            selected = [term for term in term_plan.get('terms', []) if term.get('first_section') == args.k or term.get('zh') in scope_text
                        or re.search(r'(?<![\w.])' + re.escape(str(term.get('id'))) + r'(?![\w.])', writer_points)]
            planned_terms = dumps_records([{key: term.get(key, '') for key in ('id', 'zh', 'orig', 'gloss', 'role', 'example_src', 'depends_on', 'first_section', 'confusable_with', 'alias_ban', 'source_lang', 'category', 'authority_sources', 'translation_note', 'analogy')} for term in selected])

    if writing:  # physical de-translation isolation must be *verified*, not assumed
        allow = [t.get('orig') for t in all_terms] + [t.get('orig') for t in (term_plan or {}).get('terms', []) if isinstance(t, dict)]
        outline_blob = '\n'.join(str(sec.get(key, '')) for key in ('sub_question', 'core_content', 'conclusion', 'chain_role', 'inherits', 'open_question')) + '\n' + prohibited_text if sec else ''
        surfaces = {'承重清单/讲解单元': writer_points, '上一节结尾': tail, '大纲字段': outline_blob}
        for label, blob in surfaces.items():
            for snippet in source_language_leaks(blob, allow, min_words=5, source_lang=source_lang)[:3]:
                violations.append(f"English leakage / source-language leakage into writer sheet ({label}): {snippet!r}; rewrite it in Chinese in points/units/outline")
        if args.leak_source and Path(args.leak_source).exists():
            hits = source_overlap_snippets('\n'.join(surfaces.values()), Path(args.leak_source).read_text(encoding='utf-8'), source_lang, allow)
            if hits:
                violations.append(f"verbatim 5-word source overlap in writer sheet: {hits[0]!r} (+{len(hits) - 1} more)")

    values = {
        '本节任务': f"第 {args.k} 节，共 {n} 节",
        '本节位置': position,
        '文风与体裁基调': _style_guidance(chapter_dir, source_lang),
        '本节子问题': sec.get('sub_question', '') if sec else '',
        '本节核心内容': sec.get('core_content', '') if sec else '',
        '本节应到达的结论': sec.get('conclusion', '') if sec else '',
        '本节承担的链段': sec.get('chain_role', '') if sec else '',
        '禁写清单': prohibited_text,
        '全文核心问题': state.get('thesis', outline.get('thesis', '全章核心论证')),
        '已定术语表': ledger_text,
        '承接的遗留问题': inherits,
        '本节应留下的问题': open_question,
        '上一节结尾': tail,
        '下一节子问题': next_sub,
        '源材料': material,
        '字数要求': str(sec.get('budget', 0) if sec else 0),
    }

    if args.profile == 'v2':
        values['参考篇幅'] = str(sec.get('budget', 0) if sec else 0)
        values['承重清单'] = writer_points
        values['术语计划'] = planned_terms or '本节无新术语或沿用既有词表'
        if writing:
            values.pop('源材料', None)
    elif writing:
        values.pop('源材料', None)

    sheet = fill(template, values)
    ok = not violations
    if not ok and Path(args.out).exists():
        Path(args.out).unlink()  # never leave a stale sheet next to a failure
    if ok:
        with io.open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(sheet + '\n')

    print(json.dumps({'ok': ok, 'violations': violations, 'task_sheet': args.out if ok else None}, ensure_ascii=False))
    return 0 if ok else 1


def _style_guidance(chapter_dir, source_lang):
    from workspace_config import load_config
    profile = load_config(chapter_dir)['book'].get('style_profile', {})
    family = profile.get('genre_family', 'humanities_scholarly') if isinstance(profile, dict) else 'humanities_scholarly'
    guidance = {
        'analytic_arg': '清朗、利落、体面的现代书面白话；冷静析理，句序体现条件方向和量词辖域，保留论证步骤与案例功能。',
        'humanities_scholarly': '清朗、利落、体面的现代书面白话；从具体处境推进概念分析，判断明确而经验限定有分寸。',
        'continental_critique': '清朗、利落、体面的现代书面白话；拆开多重嵌套定语与名词化表达，沿话题链还原现象描写和概念张力。',
        'narrative_nonfiction': '清朗、利落、体面的现代书面白话；用时间线、场景和人物行动推进，事理融入叙事，不添加教案式概念表。',
        'literary_fiction': '清朗、利落、体面的现代书面白话；贴合原作叙述呼吸、感官细节、对话潜台词和留白，不替作者解释。',
    }.get(family, '清朗、利落、体面的现代书面白话；依原作体裁调整叙述和推理节奏。')
    source_hint = {
        'de': '处理德语长定语和名词化时拆开重组',
        'fr': '处理法语长定语和嵌套从句时拆开重组',
        'es': '处理西班牙语从句和长定语时按中文话题链重组',
        'ru': '处理俄语长定语和从句时拆开重组',
        'ja': '按中文话题链重组日语省略主语和修饰关系',
    }.get(source_lang, '按中文话题链重组从句和长定语')
    description = profile.get('description', '').strip() if isinstance(profile, dict) else ''
    profile_hint = f"全书基调：{description}。" if description else ''
    preference = '优先直接陈述；能自然表达时少用“不是……而是”“不仅……还”等固定对举或递进格式，并优先少用冒号、分号和破折号。若会损失原文逻辑、否定范围、条件、让步、模态、观点归属或原生修辞，则保留必要形式。'
    return f"{guidance}{profile_hint}{source_hint}；{preference}关系清楚时不补显性连接词，保留原文逻辑算子与修辞。"


if __name__ == '__main__':
    sys.exit(main())

