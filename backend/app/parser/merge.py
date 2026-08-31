"""跨块、跨栏、跨页的段落合并。

LaTeX 生成的 PDF 会把一个自然段拆成多个块：实测第 4 页出现
"We evaluate LLMs as prompted three-way classi-" 与 "fiers. The primary..."
两个独立块。若不合并就送去翻译，译文会被拦腰截断且语义丢失。

合并后原块仍保留在页面里（geometry 是渲染层回流所必需的），
只是标记 merged_into 并置 translate=False，由段首块承载完整文本。
"""
from __future__ import annotations

import re

from .extract import stitch_hyphen
from .model import Block, BlockType

# 句末标点：中英文都算。以此结尾说明段落已完结，不应与下一块合并。
_SENT_END = re.compile(r"[.!?;:。！？；：)\]}”’\"']\s*$")
_ENDS_HYPHEN = re.compile(r"[A-Za-z]-$")
# 下一块以小写字母 / 中文 / 闭合括号开头，才可能是续写
_STARTS_CONT = re.compile(r"^[a-z一-鿿),;:\]]")

_MERGEABLE = {BlockType.BODY, BlockType.LIST}


def _can_merge(prev: Block, cur: Block) -> bool:
    if prev.type not in _MERGEABLE or cur.type is not BlockType.BODY:
        return False
    if prev.lang != cur.lang:
        return False
    p, c = prev.text.rstrip(), cur.text.lstrip()
    if not p or not c:
        return False
    # 断词：上块以 "字母-" 结尾，下块小写开头
    if _ENDS_HYPHEN.search(p) and c[:1].islower():
        return True
    # 未完句：上块无句末标点，下块以小写或中文续写
    if not _SENT_END.search(p) and _STARTS_CONT.match(c):
        return True
    return False


def _stitch(head: str, tail: str, hyphen_vocab: set[str], words: set[str]) -> str:
    head, tail = head.rstrip(), tail.lstrip()
    if head.endswith("-") and len(head) >= 2 and head[-2].isalnum():
        return stitch_hyphen(head, tail, hyphen_vocab, words)
    if head and tail and "一" <= head[-1] <= "鿿":
        return head + tail
    return head + " " + tail


def merge_paragraphs(
    ordered: list[Block],
    hyphen_vocab: set[str] | None = None,
    words: set[str] | None = None,
) -> None:
    """就地合并。ordered 必须是全文阅读顺序（跨页连续）。"""
    hyphen_vocab = hyphen_vocab or set()
    words = words or set()
    head: Block | None = None
    for blk in ordered:
        if head is not None and _can_merge(head, blk):
            head.text = _stitch(head.text, blk.text, hyphen_vocab, words)
            head.merged_from.append(blk.id)
            blk.merged_into = head.id
            blk.translate = False
            continue
        head = blk
