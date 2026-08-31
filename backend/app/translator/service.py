"""翻译编排：批处理、缓存、术语表、失败降级。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import settings
from ..parser.model import Block
from .base import OpenAICompatProvider, ProviderError, Usage, parse_segments
from .cache import TranslationCache
from .glossary import build_glossary, extract_terms, format_glossary
from .providers import get_provider

log = logging.getLogger(__name__)

#: 单批上限。批越大越省 prompt 开销，但一旦解析失败重试代价也越大。
MAX_BATCH_CHARS = 2000
MAX_BATCH_SEGMENTS = 10

_SYSTEM = """你是专业的学术论文翻译，把英文准确译成简体中文。

要求：
1. 忠实、通顺、术语准确，保持学术语体，不添加原文没有的内容。
2. 保留原文中的数字、公式、变量名、引用标记（如 (Wang et al., 2023)、Table 2、Figure 1）。
3. 保留原文中已有的中文内容，原样输出，不要改写。
4. 人名、机构名、模型名、产品名保留原文。
5. 只翻译，不解释、不评论、不补充。

严格输出 JSON 数组，每个元素形如 {"id":<编号>,"zh":"<译文>"}，
数组长度必须与输入段落数一致，不要输出任何其他内容。"""

#: 单段降级用。不要求 JSON —— 实测单段时模型极易改用 "[0] 译文" 或裸对象，
#: 与其和它较劲格式，不如直接收纯文本，反而更稳。
_SYSTEM_SINGLE = """你是专业的学术论文翻译，把英文准确译成简体中文。

要求：
1. 忠实、通顺、术语准确，保持学术语体，不添加原文没有的内容。
2. 保留原文中的数字、公式、变量名、引用标记（如 (Wang et al., 2023)、Table 2、Figure 1）。
3. 保留原文中已有的中文内容，原样输出，不要改写。
4. 人名、机构名、模型名、产品名保留原文。

只输出译文本身，不要编号、不要 JSON、不要引号包裹、不要任何解释。"""


@dataclass
class TranslateResult:
    translated: int = 0
    from_cache: int = 0
    failed: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    api_calls: int = 0


def _batch(blocks: list[Block]) -> list[list[Block]]:
    """按字符数与条数切批，保持阅读顺序以维持语境连贯。"""
    batches, cur, size = [], [], 0
    for b in blocks:
        n = len(b.text)
        if cur and (size + n > MAX_BATCH_CHARS or len(cur) >= MAX_BATCH_SEGMENTS):
            batches.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += n
    if cur:
        batches.append(cur)
    return batches


class Translator:
    def __init__(
        self,
        provider: OpenAICompatProvider | None = None,
        cache: TranslationCache | None = None,
        lang: str = "zh",
    ):
        self.provider = provider or get_provider()
        self.cache = cache or TranslationCache()
        self.lang = lang
        self.glossary_text = ""

    # ---------- 术语表 ----------

    def prepare_glossary(self, doc_hash: str, blocks: list[Block]) -> dict[str, str]:
        cached = self.cache.get_glossary(doc_hash)
        if cached:
            self.glossary_text = format_glossary(cached)
            return cached
        terms = extract_terms([b.text for b in blocks])
        mapping = build_glossary(self.provider, terms, model=settings.qwen_model_gloss)
        if mapping:
            self.cache.put_glossary(doc_hash, mapping)
        self.glossary_text = format_glossary(mapping)
        return mapping

    # ---------- 翻译 ----------

    def _system(self, single: bool = False) -> str:
        base = _SYSTEM_SINGLE if single else _SYSTEM
        return base + ("\n\n" + self.glossary_text if self.glossary_text else "")

    def _call_batch(self, batch: list[Block]) -> tuple[dict[int, str], Usage]:
        user = "\n\n".join(f"[{i}] {b.text}" for i, b in enumerate(batch))
        raw, usage = self.provider.chat(self._system(), user, max_tokens=4000)
        return parse_segments(raw, len(batch)), usage

    def _translate_one(self, block: Block) -> tuple[str | None, Usage]:
        """降级路径：批量结果对不齐时逐条重来，宁可慢也不能错位。"""
        try:
            raw, usage = self.provider.chat(
                self._system(single=True), block.text, max_tokens=4000
            )
            text = raw.strip().strip("`").strip()
            return (text or None), usage
        except Exception as exc:
            log.warning("单条翻译失败 %s: %s", block.id, exc)
            return None, Usage()

    def translate_blocks(
        self, blocks: list[Block], on_progress=None
    ) -> TranslateResult:
        result = TranslateResult()
        model = self.provider.model
        pending: list[Block] = []

        # 先吃缓存：对照阅读看过的页，导出时不必重付一次钱
        hits = self.cache.get_many([b.text for b in blocks], self.lang, self.provider.name, model)
        for b in blocks:
            if b.text in hits:
                b.translation = hits[b.text]
                result.from_cache += 1
            else:
                pending.append(b)

        for batch in _batch(pending):
            fresh: list[tuple[str, str]] = []
            try:
                got, usage = self._call_batch(batch)
                result.usage += usage
                result.api_calls += 1
            except Exception as exc:
                log.warning("批量翻译失败，降级为逐条：%s", exc)
                got = {}

            # 返回条数对不上就逐条补，绝不让译文与段落错位
            missing = [i for i in range(len(batch)) if i not in got or not got[i]]
            if missing and len(missing) == len(batch):
                for i in missing:
                    text, usage = self._translate_one(batch[i])
                    result.usage += usage
                    result.api_calls += 1
                    if text:
                        got[i] = text
            elif missing:
                log.warning("批量少返回 %d 条，逐条补齐", len(missing))
                for i in missing:
                    text, usage = self._translate_one(batch[i])
                    result.usage += usage
                    result.api_calls += 1
                    if text:
                        got[i] = text

            for i, blk in enumerate(batch):
                if i in got and got[i]:
                    blk.translation = got[i]
                    fresh.append((blk.text, got[i]))
                    result.translated += 1
                else:
                    result.failed.append(blk.id)

            self.cache.put_many(fresh, self.lang, self.provider.name, model)
            if on_progress:
                on_progress(result)

        return result

    def close(self) -> None:
        self.provider.close()
