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
    # 长标题被排版拆成多块，分别翻译会各自丢掉半句语义，必须先拼回整句
    if prev.type is BlockType.TITLE and cur.type is BlockType.TITLE:
        return True
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


#: 续行缩进超过首行这么多 pt，即判为同一条文献的续写
_HANGING_INDENT = 4.0


def merge_references(ordered: list[Block], hyphen_vocab=None, words=None) -> None:
    """把悬挂缩进的参考文献条目并成一条。

    文献表用悬挂缩进排版：每条首行齐左，续行缩进。PyMuPDF 会把它们切成
    独立的块，于是一条文献变成 "Helmut Appel, Alexander L Gerlach, and Jan
    Crusius." 与 "2016. The interplay between..." 两块 —— 分开翻译会把
    作者与标题割裂。按每栏内文献块的最左位置识别首行，其余归为续写。
    """
    hyphen_vocab = hyphen_vocab or set()
    words = words or set()

    refs = [b for b in ordered if b.type is BlockType.REFERENCE]
    if not refs:
        return
    # 每（页, 栏）的齐左位置。跨栏、跨页续写的缩进量不同，必须分组求。
    flush: dict[tuple[int, int], float] = {}
    for b in refs:
        key = (b.page, b.column)
        flush[key] = min(flush.get(key, b.bbox[0]), b.bbox[0])

    head: Block | None = None
    for b in ordered:
        if b.type is not BlockType.REFERENCE:
            head = None
            continue
        left = flush.get((b.page, b.column))
        if head is not None and left is not None and b.bbox[0] > left + _HANGING_INDENT:
            head.text = _stitch(head.text, b.text, hyphen_vocab, words)
            head.merged_from.append(b.id)
            b.merged_into = head.id
            b.translate = False
        else:
            head = b
