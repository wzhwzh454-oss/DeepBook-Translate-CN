import argparse
import json
import math
import re
import statistics
from pathlib import Path

from check_draft import FORBIDDEN, USER_FORBIDDEN
from check_terms import faithful_paragraphs
import textutil
from language import expected_zh_chars
from workspace_config import load_config, source_language


PATTERNS = {
    "de_chain": r"(?:[^，。？！；：\n]{0,8}的){3}[^，。？！；：\n]{0,4}",
    "passive": r"被[^，。？！；]{1,20}(?:所|进行|予以|加以)|受到[^，。？！；]{1,16}的",
    "light_verb": r"(?:进行|予以|加以|作出|做出)(?:进一步的?)?(?:分析|讨论|考察|解释|判断|评价|说明|区分|研究|拒绝|否定|决定)",
    "nominal_chain": r"(?:[\u4e00-\u9fff]{1,5}[性化者]){3}",
    "preposition": r"就[^，。？！]{1,12}而言|对于[^，。？！]{1,12}来说|作为[^，。？！]{1,12}的|在[^，。？！]{1,12}下",
    "empty_turn": r"值得注意|非常重要|总之|总而言之|综上所述|接下来我们|这充分体现|深刻揭示",
    "fake_reversal": r"不是[^。？！]{1,30}而是",
}
CONNECTIVES = re.compile(r"因此|然而|此外|另外|与此同时|正因如此|由此可见|换言之|综上所述")
CONNECTIVE_PAIR = re.compile(r"由于.{0,60}因此|之所以.{0,40}是因为")
DISCLAIMER = re.compile(r"(?:这)?并不意味着.{0,70}(?:也不是说|也不意味着|也不代表)|不代表.{0,40}(?:也不是说|也不等于)")
DEAD_METAPHORS = {
    "glass_case_specimen": "玻璃柜里的僵死标本|玻璃柜中的僵死标本",
    "scattered_sand": "一盘散沙",
    "neutral_mirror": "不偏不倚的镜子|一面镜子",
    "public_abacus": "公共算盘",
    "medical_checkup": "体检表",
    "cold_scalpel": "冰冷的手术刀|手术刀",
    "colored_glasses": "有色眼镜",
    "filter": "滤镜",
    "canvas": "画布",
    "porcelain_cup": "青瓷茶杯",
    "rainy_street": "雨夜街角",
}
REGISTER_POLLUTION = re.compile(r"说白了|说穿了|打根上|肚子里那点劲儿|一地鸡毛|盘出包浆|找补|不妨|你看|焊死|钉死|碾碎|撕裂|一刀切断|淤积")
HIGH_SATURATION = re.compile(r"彻彻底底|重若千钧|断了一瞬|行事做派|毫无疑问|振聋发聩|震撼|惊人|竟然?|偏偏|唯独|绝非.{0,20}也不是")
DEFAULTS = {"sent_p50_max": 24, "sent_p90_max": 45, "sent_hard": 65, "para_soft": 180, "para_hard": 300}


def percentile(values, quantile):
    if not values:
        return 0
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def check_readability(text, thresholds=None, candidates=False, source_words=None, coverage=None, source_lang='en', source_points_text=''):
    limits = {**DEFAULTS, **(thresholds or {})}
    paragraphs = faithful_paragraphs(text)
    sentences = [sentence for paragraph in paragraphs for sentence in textutil.split_sentences(paragraph) if not re.fullmatch(r'[“「『"].*[”」』"]', sentence.strip(), re.S)]
    lengths = [textutil.cjk_count(sentence) for sentence in sentences]
    paragraph_lengths = [textutil.cjk_count(paragraph) for paragraph in paragraphs]
    total = sum(textutil.cjk_count(paragraph) for paragraph in paragraphs)
    violations = []
    advisories = []
    analysis_text = '\n\n'.join(paragraphs)
    matches = {name: list(re.finditer(pattern, analysis_text)) for name, pattern in PATTERNS.items()}
    candidate_items = []
    source_points_compact = textutil.compact(source_points_text)
    for index, (sentence, length) in enumerate(zip(sentences, lengths)):
        if length > limits["sent_hard"]:
            advisories.append(f"review sentence {index + 1}: {length} CJK > {limits['sent_hard']}: {sentence}")
        reasons = []
        if length > 50:
            reasons.append("long_sentence")
        if sentence.count("，") + sentence.count(",") >= 6:
            reasons.append("comma_chain")
        for name in ("de_chain", "passive", "light_verb"):
            if re.search(PATTERNS[name], sentence):
                reasons.append(name)
        if reasons:
            candidate_items.append({"kind": "sentence", "index": index + 1, "quote": sentence, "reasons": reasons, "before": sentences[index - 1] if index else "", "after": sentences[index + 1] if index + 1 < len(sentences) else ""})
    for index, (paragraph, length) in enumerate(zip(paragraphs, paragraph_lengths)):
        count = len(textutil.split_sentences(paragraph))
        if length > limits["para_hard"]:
            advisories.append(f"review paragraph {index + 1}: {length} CJK > {limits['para_hard']}")
        if length > limits["para_soft"] or count > 7:
            advisories.append(f"paragraph {index + 1}: consider a functional paragraph break")
            candidate_items.append({"kind": "paragraph", "index": index + 1, "quote": paragraph, "reasons": ["long_paragraph"]})
        style_reasons = []
        sentence_list = [s.strip() for s in textutil.split_sentences(paragraph) if s.strip()]
        if (len(CONNECTIVES.findall(paragraph)) >= 3 or sum(bool(CONNECTIVES.match(s)) for s in sentence_list) >= 2
                or CONNECTIVE_PAIR.search(paragraph)):
            style_reasons.append("connective_overload")
        for sign, reason in (("——", "punctuation_crutch_dash"), ("：", "punctuation_crutch_colon"), ("；", "punctuation_crutch_semicolon")):
            if sign in paragraph:
                style_reasons.append(reason)
        if DISCLAIMER.search(paragraph[-120:]):
            style_reasons.append("disclaimer_tail")
        if re.search(r"值得注意的是|需要指出的是|不难发现|接下来我们|原因如下[：:]", paragraph):
            style_reasons.append("announcement_filler")
        if re.search(r"(?:总之|综上所述|这正是).{0,40}(?:意义|价值|重要性)", paragraph[-100:]):
            style_reasons.append("disclaimer_tail")
        if len(sentence_list) >= 4:
            short_run = 0
            for sentence in sentence_list:
                if textutil.cjk_count(sentence) <= 18:
                    short_run += 1
                    if short_run >= 4:
                        style_reasons.append("choppy_chain")
                        break
                else:
                    short_run = 0
        starts = [re.sub(r"^(?:因此|然而|此外|另外|与此同时)[，,]?\s*", "", s)[:4] for s in sentence_list]
        if any(prefix and starts.count(prefix) >= 3 for prefix in set(starts)):
            style_reasons.append("anaphora_repeat")
        for label, pattern in DEAD_METAPHORS.items():
            for match in re.finditer(pattern, paragraph):
                phrase = match.group(0)
                if textutil.compact(phrase) not in source_points_compact:
                    style_reasons.append("dead_metaphor:" + label)
        if REGISTER_POLLUTION.search(paragraph):
            style_reasons.extend(("register_pollution", "register_pollution:" + REGISTER_POLLUTION.search(paragraph).group(0)))
        if HIGH_SATURATION.search(paragraph):
            style_reasons.append("high_saturation")
        if style_reasons:
            candidate_items.append({"kind": "style", "index": index + 1, "quote": paragraph, "reasons": sorted(set(style_reasons))})
    for phrase in FORBIDDEN:
        if phrase in analysis_text:
            destination = violations if phrase in USER_FORBIDDEN else advisories
            destination.append(f"{'forbidden' if phrase in USER_FORBIDDEN else 'review'} phrase: {phrase}")
    median = statistics.median(lengths) if lengths else 0
    p90 = percentile(lengths, 0.9)
    for name, value, limit in (("sentence median", median, limits["sent_p50_max"]), ("sentence p90", p90, limits["sent_p90_max"])):
        if value > limit:
            advisories.append(f"{name} {value:.1f} > {limit}; interpret alongside meaning and rhythm")
    cvs = []
    for paragraph in paragraphs:
        values = [textutil.cjk_count(sentence) for sentence in textutil.split_sentences(paragraph)]
        if len(values) > 1 and statistics.mean(values):
            cvs.append(statistics.pstdev(values) / statistics.mean(values))
    metrics = {
        "cjk_count": total,
        "sentence_count": len(sentences),
        "sent_p50": median,
        "sent_p90": p90,
        "sent_max": max(lengths, default=0),
        "long_sentence_ratio": sum(length > 45 for length in lengths) / len(lengths) if lengths else 0,
        "para_p50": statistics.median(paragraph_lengths) if paragraph_lengths else 0,
        "para_p90": percentile(paragraph_lengths, 0.9),
        "para_max": max(paragraph_lengths, default=0),
        "para_mean": statistics.mean(paragraph_lengths) if paragraph_lengths else 0,
        "sent_over_60_ratio": sum(length > 60 for length in lengths) / len(lengths) if lengths else 0,
        "para_over_250": sum(length > 250 for length in paragraph_lengths),
        "single_sentence_ratio": sum(len(textutil.split_sentences(paragraph)) == 1 for paragraph in paragraphs) / len(paragraphs) if paragraphs else 0,
        "comma_chains": sum(sentence.count("，") + sentence.count(",") >= 6 for sentence in sentences),
        "rhythm_cv_mean": statistics.mean(cvs) if cvs else 0,
        "parallel_triples": sum(len(sentences[index:index + 3]) == 3 and len({sentence[:2] for sentence in sentences[index:index + 3]}) == 1 for index in range(max(0, len(sentences) - 2))),
        "paragraph_summaries": sum(bool(re.search(r"总之|可见|由此|因而可知", textutil.split_sentences(paragraph)[-1])) for paragraph in paragraphs),
        **{f"{name}_per_1000": len(found) * 1000 / total if total else 0 for name, found in matches.items()},
    }
    metrics['length_ratio'] = total / expected_zh_chars(source_words, source_lang) if source_words and source_words > 0 else None
    if metrics['length_ratio'] is not None and not 0.85 <= metrics['length_ratio'] <= 1.25:
        advisories.append('length ratio outside initial 0.85–1.25 guidance; coverage and comprehension decide adequacy')
    if coverage is not None:
        entries = coverage.get('entries', [])
        loads = [len({entry['id'] for entry in entries if entry.get('status') in {'完整', '弱化'} and entry.get('evidence') and textutil.compact(entry['evidence']) in textutil.compact(paragraph)}) for paragraph in paragraphs]
        metrics['bearing_per_paragraph_max'] = max(loads, default=0)
        metrics['bearing_per_paragraph_mean'] = statistics.mean(loads) if loads else 0
        if any(load > 3 for load in loads):
            advisories.append('paragraph bearing load exceeds initial target 3; inspect full audit mapping')
        metrics['bearing_density_scope'] = 'unique audited item ids with evidence inside paragraph; not a semantic load measure'
    return {"ok": not violations, "violations": violations, "advisories": advisories, "metrics": metrics, "thresholds": limits, "candidates": candidate_items if candidates else [], "heuristic": True}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--out-json")
    parser.add_argument("--config")
    parser.add_argument("--candidates", action="store_true")
    parser.add_argument("--marked", action="store_true")
    parser.add_argument("--source-words", type=int)
    parser.add_argument("--coverage-json")
    parser.add_argument("--points")
    arguments = parser.parse_args(argv)
    config = json.loads(Path(arguments.config).read_text(encoding="utf-8")) if arguments.config else load_config(arguments.text)
    lang = config.get("book", {}).get("source_lang", source_language(arguments.text))
    limits = config.get("translation", config).get("readability", {})
    text = Path(arguments.text).read_text(encoding="utf-8")
    coverage = json.loads(Path(arguments.coverage_json).read_text(encoding='utf-8')) if arguments.coverage_json else None
    points_text = Path(arguments.points).read_text(encoding='utf-8') if arguments.points else ''
    result = check_readability(text, limits, arguments.candidates, arguments.source_words, coverage, lang, points_text)
    if arguments.marked:
        from apply_patches import split_marked
        sections = split_marked(text)
        result = check_readability("\n\n".join(body for number, body in sections), limits, source_words=arguments.source_words, coverage=coverage, source_lang=lang, source_points_text=points_text)
        result["candidates"] = [{"k": number, **candidate} for number, body in sections for candidate in check_readability(body, limits, True, source_points_text=points_text)["candidates"]] if arguments.candidates else []
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.out_json:
        Path(arguments.out_json).write_text(output, encoding="utf-8")
    print(output)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

