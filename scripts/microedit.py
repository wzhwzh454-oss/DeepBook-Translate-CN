import re
import unicodedata


QUALIFIERS = ("只", "仅", "才", "所有", "每个", "任何", "某些", "有些", "至少", "至多", "可能", "必然", "必须", "一定", "通常", "除非", "当且仅当", "如果", "只有", "并非", "不", "没有", "未", "除了", "总是", "从不")
SUBJECTS = re.compile(r"(?:他们|她们|它们|这个|这些|作者|论敌|他|她|它|这|该)+\Z")
OPERATOR_CLASSES = {
    "universal": re.compile(r"所有|每个|每一|任何|一切|凡是|全部|无一例外|总是"),
    "existential": re.compile(r"有些|某些|有的|至少有|存在"),
    "negation": re.compile(r"并非|绝非|不是|没有|并不|未曾|从不|绝不|无法|不能|不会|不再|并未|尚未|不可|难以|很难|未|非"),
    "necessary_cond": re.compile(r"只有|仅当|除非|唯有|必须"),
    "sufficient_cond": re.compile(r"只要|如果|假如|一旦|倘若"),
    "iff": re.compile(r"当且仅当|充要|恰好当"),
    "possible": re.compile(r"可能|或许|也许|似乎|大概|未必|能够|可以"),
    "necessary": re.compile(r"必然|一定|必定|不可避免|无疑"),
    "limiter": re.compile(r"至多|至少|僅僅|仅仅|只是|尚未|只(?!有|当|要)|仅(?!当)"),
}


def substantive(text):
    return "".join(character for character in text if not character.isspace() and not unicodedata.category(character).startswith("P"))


def check_microedit(original, replacement, terms=()):
    old = substantive(original)
    new = substantive(replacement)
    position = 0
    additions = []
    buffer = []
    for character in new:
        if position < len(old) and character == old[position]:
            if buffer:
                additions.append("".join(buffer))
                buffer = []
            position += 1
        else:
            buffer.append(character)
    if buffer:
        additions.append("".join(buffer))
    if position != len(old):
        return False
    if sum(map(len, additions)) > 8 or any(not SUBJECTS.fullmatch(value) for value in additions):
        return False
    protected = set(QUALIFIERS)
    for term in terms:
        if isinstance(term, dict):
            protected.update(value for value in (term.get("zh"), term.get("orig")) if value)
        elif term:
            protected.add(term)
    return all(old.casefold().count(value.casefold()) == new.casefold().count(value.casefold()) for value in protected)


def check_semantic_preservation(original, replacement, terms=()):
    """Guard broader style edits against loss or reversal of key operators and terms."""
    for name, pattern in OPERATOR_CLASSES.items():
        if len(pattern.findall(original)) != len(pattern.findall(replacement)):
            return False
    from operators import operator_parity
    if any("scope inversion" in issue or "modal inversion" in issue
           for issue in operator_parity(original, "", replacement)):
        return False
    for term in terms:
        if isinstance(term, dict):
            value = term.get("zh")
        else:
            value = term
        if value and original.count(value) and replacement.count(value) < 1:
            return False
    return True

