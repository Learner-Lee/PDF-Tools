"""术语表：保证全篇译名一致。

长文档分批翻译时，同一个专有名词在不同批次里很容易被译成不同说法。
做法是先扫全文抽出高频专有名词与缩写，用一次调用敲定统一译名，
再把这份对照注入每一批的 system prompt。
"""
from __future__ import annotations

import re
from collections import Counter

from .base import OpenAICompatProvider, parse_json_array

# 全大写缩写：LLM、NLP、XHS-SCoRE、GPT-5
_RE_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[-‑][A-Za-z0-9]+)*\b")
# 专有名词：大写开头的词（可含连字符），排除句首误判靠频次过滤
_RE_PROPER = re.compile(r"\b[A-Z][a-z]{2,}(?:[-‑][A-Z]?[a-z]+)*\b")

#: 高频但无需统一译名的常见句首词
_STOP = {
    "The", "This", "That", "These", "Those", "There", "Then", "They", "Their",
    "We", "Our", "It", "Its", "In", "For", "From", "With", "When", "While",
    "However", "Table", "Figure", "Section", "Appendix", "First", "Second",
    "Third", "Finally", "Both", "Each", "All", "Some", "Such", "Because",
    "Although", "After", "Before", "Since", "Given", "Using", "Overall",
    "Beyond", "Under", "Across", "Based", "Results", "Model", "Models",
}

_SYSTEM = (
    "你是学术翻译的术语专家。用户会给出一篇英文论文中的高频术语与专有名词。"
    "请为每个词给出该领域最通行的中文译名。"
    "若该词是应当保留原文的缩写、模型名、产品名或代号（如 GPT-5、LLM、UP/DOWN 等标签），"
    'rendering 直接填原词。'
    '严格输出 JSON 数组，元素形如 {"term":"<原词>","rendering":"<中文或原词>"}，不要输出其他内容。'
)


_RE_LOWER_TOKEN = re.compile(r"\b[a-z]{3,}\b")


def extract_terms(texts: list[str], min_freq: int = 3, limit: int = 60) -> list[str]:
    """抽取需要统一译名的专有名词与缩写。

    关键的去噪判据：若某个大写词的小写形式也在文中出现过（social / Social），
    说明它只是句首大写的普通词，不是专有名词。不做这一步，术语表会被
    Social、Human、Full、Participants 这类词淹没，白白污染每一批的 prompt。
    """
    lower_seen: set[str] = set()
    for t in texts:
        lower_seen.update(m.group(0) for m in _RE_LOWER_TOKEN.finditer(t))

    counter: Counter[str] = Counter()
    for t in texts:
        for m in _RE_ACRONYM.finditer(t):
            counter[m.group(0)] += 2      # 缩写权重更高，最需要统一
        for m in _RE_PROPER.finditer(t):
            w = m.group(0)
            if w in _STOP or w.lower() in lower_seen:
                continue
            counter[w] += 1
    return [w for w, c in counter.most_common(limit) if c >= min_freq]


def build_glossary(
    provider: OpenAICompatProvider, terms: list[str], model: str | None = None
) -> dict[str, str]:
    if not terms:
        return {}
    raw, _ = provider.chat(
        _SYSTEM, "\n".join(terms), temperature=0.0, max_tokens=2000, model=model
    )
    try:
        items = parse_json_array(raw)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for it in items:
        term, rendering = str(it.get("term", "")).strip(), str(it.get("rendering", "")).strip()
        if term and rendering and term != rendering:
            out[term] = rendering
    return out


def format_glossary(mapping: dict[str, str], limit: int = 40) -> str:
    if not mapping:
        return ""
    lines = [f"{k} → {v}" for k, v in list(mapping.items())[:limit]]
    return "术语对照（必须严格遵守）：\n" + "\n".join(lines)
