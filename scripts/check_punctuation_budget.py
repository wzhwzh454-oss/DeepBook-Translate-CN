# -*- coding: utf-8 -*-
"""Compare chapter-body punctuation counts with the numbered source chapter."""
import argparse
import json
import re
import sys
from pathlib import Path


MARKS = {
    "colon": {":", "："},
    "semicolon": {";", "；"},
}
LABELS = {"colon": "冒号", "semicolon": "分号", "dash": "破折号"}
GLOSSARY_HEADING = re.compile(
    r"^(?:术语表|词汇表|术语与概念台账|核心术语表)(?:\s|[:：]|（|\(|$)"
    r"|^glossary(?:\s+and\s+concepts)?(?:\b|$)", re.I)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
SOURCE_MARKER = re.compile(r"^\s*\[P(\d+)\]\s*(.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
FENCE = re.compile(r"^\s{0,3}(```+|~~~+)")
INLINE_CODE = re.compile(r"(?<!`)`+[^`]*?`+(?!`)")
LINK_DESTINATION = re.compile(r"\]\([^)]*\)")
ANGLE_URL = re.compile(r"<https?://[^>]+>", re.I)
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")


def _without_comments(text):
    return re.sub(r"(?s)<!--.*?-->", lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)


def source_body(text):
    """Keep only numbered source paragraphs; headings and preface are out of scope."""
    paragraphs = []
    paragraph_ids = []
    current = None
    for line in _without_comments(text).splitlines():
        match = SOURCE_MARKER.match(line)
        if match:
            if current is not None:
                paragraphs.append("\n".join(current))
            paragraph_ids.append(int(match.group(1)))
            current = [match.group(2)]
        elif current is not None:
            current.append(line)
    if current is not None:
        paragraphs.append("\n".join(current))
    return "\n".join(paragraphs), paragraph_ids


def _markdown_line(line):
    if TABLE_RULE.match(line):
        return ""
    line = INLINE_CODE.sub("", line)
    line = LINK_DESTINATION.sub("]", line)
    line = ANGLE_URL.sub("", line)
    line = HTML_TAG.sub("", line)
    line = re.sub(r"^\s*\[P\d+\]\s*", "", line)
    if "|" in line:
        line = line.strip().strip("|").replace("|", " ")
    return line


def translation_body(text):
    """Drop Markdown metadata and non-body structures while keeping table cell text."""
    text = _without_comments(text)
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                start = index + 1
                break

    # Preserve blank placeholders for excluded lines so findings retain their
    # line numbers in the original Markdown file.
    output = [""] * start
    in_fence = False
    fence_token = None
    glossary_level = None
    for line in lines[start:]:
        fence = FENCE.match(line)
        if fence:
            token = fence.group(1)[0]
            if not in_fence:
                in_fence, fence_token = True, token
            elif token == fence_token:
                in_fence, fence_token = False, None
            output.append("")
            continue
        if in_fence:
            output.append("")
            continue

        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().strip("#").strip()
            if glossary_level is not None and level <= glossary_level:
                glossary_level = None
            if glossary_level is not None:
                output.append("")
                continue
            if GLOSSARY_HEADING.match(title):
                glossary_level = level
            output.append("")
            continue
        if glossary_level is not None:
            output.append("")
            continue
        if re.match(r"^\s*\[[^\]]+\]:\s*https?://", line, re.I):
            output.append("")
            continue
        output.append(_markdown_line(line))
    return "\n".join(output)


def _snippet(line, start, end, radius=36):
    left = max(0, start - radius)
    right = min(len(line), end + radius)
    excerpt = line[left:right].strip()
    return excerpt[:120]


def punctuation_occurrences(text):
    occurrences = {name: [] for name in ("colon", "semicolon", "dash")}
    line_number = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        for column, char in enumerate(line):
            for name in ("colon", "semicolon"):
                if char in MARKS[name]:
                    occurrences[name].append({
                        "line": line_number,
                        "column": column + 1,
                        "mark": char,
                        "excerpt": _snippet(line, column, column + 1),
                    })

        index = 0
        while index < len(line):
            char = line[index]
            if char == "—":
                stop = index + 1
                while stop < len(line) and line[stop] == "—":
                    stop += 1
                run_length = stop - index
                mark_count = (run_length + 1) // 2
                for offset in range(mark_count):
                    start = index + min(offset * 2, run_length - 1)
                    end = min(start + 2, stop)
                    occurrences["dash"].append({
                        "line": line_number,
                        "column": start + 1,
                        "mark": line[start:end],
                        "excerpt": _snippet(line, start, end),
                    })
                index = stop
                continue
            if char in ("–", "―"):
                if not (char == "–" and index > 0 and index + 1 < len(line)
                        and line[index - 1].isdigit() and line[index + 1].isdigit()):
                    occurrences["dash"].append({
                        "line": line_number,
                        "column": index + 1,
                        "mark": char,
                        "excerpt": _snippet(line, index, index + 1),
                    })
                index += 1
                continue
            if line.startswith("--", index):
                left_space = index == 0 or line[index - 1].isspace()
                right_space = index + 2 == len(line) or line[index + 2].isspace()
                if left_space and right_space:
                    occurrences["dash"].append({
                        "line": line_number,
                        "column": index + 1,
                        "mark": "--",
                        "excerpt": _snippet(line, index, index + 2),
                    })
                    index += 2
                    continue
            index += 1
    return occurrences


def check_texts(source_text, translation_text, source_path="<source>", translation_path="<translation>"):
    source, paragraph_ids = source_body(source_text)
    translation = translation_body(translation_text)
    issues = []
    if not paragraph_ids:
        issues.append("源文没有可识别的 [P#] 正文段落锚点；无法确认章范围，拒绝给出额度")
    if len(set(paragraph_ids)) != len(paragraph_ids):
        issues.append("源文 [P#] 正文段落编号重复；请先修复编号结构")
    if not source.strip():
        issues.append("源文正文范围为空")
    if not translation.strip():
        issues.append("译文正文范围为空")

    source_occurrences = punctuation_occurrences(source)
    translation_occurrences = punctuation_occurrences(translation)
    source_counts = {key: len(value) for key, value in source_occurrences.items()}
    translation_counts = {key: len(value) for key, value in translation_occurrences.items()}
    violations = []
    for key in ("colon", "semicolon", "dash"):
        limit = source_counts[key]
        actual = translation_counts[key]
        if actual <= limit:
            continue
        over_limit = []
        for ordinal, occurrence in enumerate(translation_occurrences[key], 1):
            if ordinal > limit:
                over_limit.append({"ordinal": ordinal, **occurrence})
        violations.append({
            "mark_type": key,
            "label": LABELS[key],
            "source_limit": limit,
            "translation_count": actual,
            "excess": actual - limit,
            "over_limit_locations": over_limit,
        })
        sample = ", ".join("L%d %s" % (item["line"], item["mark"]) for item in over_limit[:8])
        issues.append("%s超出独立上限：译文 %d，源文 %d，多 %d；超额序位位置：%s%s" % (
            LABELS[key], actual, limit, actual - limit, sample,
            "（完整定位见报告）" if len(over_limit) > 8 else ""))

    return {
        "ok": not issues,
        "violations": issues,
        "scope": {
            "source": "仅统计 source-numbered.md 中 [P#] 锚点正文；锚点标签、标题和锚点前材料排除。",
            "translation": "统计 Markdown 正文；标题、YAML 头、代码块、HTML 注释、术语表章节、表格分隔语法和链接目标排除；表格单元格正文保留。",
            "normalization": "全/半角冒号与分号各自归一计数；中文连续两个 em dash（——）按一个标记计，四个按两个；单个 em/en/horizontal bar 各计一个；数字间 en dash 与词内连字符不计。",
            "policy": "三类分别比较，额度不互换；只报告超额位置，不自动改写。",
        },
        "source": {
            "path": str(Path(source_path).resolve()) if source_path != "<source>" else source_path,
            "paragraph_ids": paragraph_ids,
            "paragraph_count": len(paragraph_ids),
            "counts": source_counts,
        },
        "translation": {
            "path": str(Path(translation_path).resolve()) if translation_path != "<translation>" else translation_path,
            "counts": translation_counts,
        },
        "limits": source_counts,
        "over_limit": violations,
    }


def check_files(source_path, translation_path):
    source_path, translation_path = Path(source_path), Path(translation_path)
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {"ok": False, "violations": ["无法读取源文正文文件：%s" % error], "over_limit": []}
    try:
        translation_text = translation_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {"ok": False, "violations": ["无法读取译文终稿：%s" % error], "over_limit": []}
    return check_texts(source_text, translation_text, source_path, translation_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="按章检查译文的三类标点独立上限")
    parser.add_argument("--source", required=True, type=Path, help="编号源文正文文件，必须含 [P#] 段落锚点")
    parser.add_argument("--translation", required=True, type=Path, help="章节整合定稿 Markdown")
    args = parser.parse_args(argv)
    report = check_files(args.source, args.translation)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
