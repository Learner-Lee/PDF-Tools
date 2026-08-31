"""块类型分类。

标题判定靠字重而非字号：实测这份 ACL 模板论文里,
"4.4 Corpus analysis" 字号 10.9 反而小于正文 11.0，只有 bold 是可靠信号。
"""
from __future__ import annotations

import re

from .model import Block, BlockType, Span

_RE_CAPTION = re.compile(r"^\s*(Figure|Fig\.|Table|Algorithm|Listing|Appendix)\s*\d+", re.I)
_RE_LIST = re.compile(r"^\s*([•·▪‣∙]|[-–—]\s|\(?[a-z0-9]{1,3}[.)]\s)")
_RE_HEADING_NUM = re.compile(r"^\s*(\d+(\.\d+)*|[A-Z](\.\d+)*)\s*\.?\s+\S")
_RE_REF_HEAD = re.compile(r"^\s*(References|Bibliography|参考文献)\s*$", re.I)
#: 附录/章节标题：字母或数字编号后跟空格与正文，如 "A Release Artifacts"、"B.1 Prompt variants"
_RE_SECTION_HEAD = re.compile(r"^\s*(Appendix\b|附录|[A-Z](\.\d+)*\s+\S|\d+(\.\d+)*\s+\S)")


def _ratio(spans: list[Span], attr: str) -> float:
    total = sum(len(s.text) for s in spans) or 1
    hit = sum(len(s.text) for s in spans if getattr(s, attr))
    return hit / total


def classify(
    block: Block,
    page_height: float,
    page_width: float,
    body_size: float,
    in_references: bool,
) -> BlockType:
    x0, y0, x1, y1 = block.bbox
    text = block.text.strip()
    spans = block.spans
    w, h = x1 - x0, y1 - y0

    # 1. 水印：又窄又高的竖排块（arXiv 侧边戳），或整体贴在页面左右边缘外侧
    if h > 3 * w and h > page_height * 0.25:
        return BlockType.WATERMARK
    if x1 < page_width * 0.08 or x0 > page_width * 0.92:
        return BlockType.WATERMARK

    # 2. 页眉页脚：贴顶或贴底的短块（页码、running head）
    if (y0 > page_height * 0.93 or y1 < page_height * 0.07) and len(text) < 120:
        return BlockType.HEADER_FOOTER

    # 3. 参考文献区：References 标题之后的一切
    if _RE_REF_HEAD.match(text):
        return BlockType.HEADING
    if in_references:
        return BlockType.REFERENCE

    # 4. 公式 / 代码：按 span 字体占比判断
    if _ratio(spans, "math") > 0.5:
        return BlockType.MATH
    if _ratio(spans, "mono") > 0.6:
        return BlockType.CODE

    # 5. 图表标题
    if _RE_CAPTION.match(text):
        return BlockType.CAPTION

    # 6. 章节标题：整块加粗 + 文本短。字号在此不可靠，故不参与判定。
    bold = _ratio(spans, "bold")
    if bold > 0.7 and len(text) < 120 and text.count("\n") == 0:
        if _RE_HEADING_NUM.match(text) or len(text) < 60:
            return BlockType.HEADING

    # 7. 列表
    if _RE_LIST.match(text):
        return BlockType.LIST

    return BlockType.BODY


def _ends_references(block: Block) -> bool:
    """判断该块是否标志着参考文献区结束。

    附录常常排在参考文献之后。若 in_references 一经置位就再不复位，
    整个附录都会被当成文献跳过翻译 —— 实测这份论文有 8 页附录因此丢失。
    参考文献条目不加粗，而附录章节标题加粗且带编号，据此区分。
    """
    text = block.text.strip()
    return (
        _ratio(block.spans, "bold") > 0.7
        and len(text) < 120
        and bool(_RE_SECTION_HEAD.match(text))
    )


def classify_page(
    blocks: list[Block],
    page_height: float,
    page_width: float,
    body_size: float,
    in_references: bool,
) -> bool:
    """就地分类整页。返回离开本页时是否仍处于参考文献区。"""
    for b in blocks:
        if in_references and _ends_references(b):
            in_references = False
        b.type = classify(b, page_height, page_width, body_size, in_references)
        if b.type is BlockType.HEADING and _RE_REF_HEAD.match(b.text.strip()):
            in_references = True
    return in_references


def mark_front_matter(blocks: list[Block]) -> None:
    """标注首页的标题与作者块。标题取首页最靠上的加粗大字块。"""
    cand = [b for b in blocks if b.type in (BlockType.BODY, BlockType.HEADING)]
    if not cand:
        return
    top = sorted(cand, key=lambda b: b.bbox[1])[:6]
    if not top:
        return
    max_size = max((max((s.size for s in b.spans), default=0) for b in top), default=0)
    for b in top:
        size = max((s.size for s in b.spans), default=0)
        if size >= max_size - 0.1 and _ratio(b.spans, "bold") > 0.5:
            b.type = BlockType.TITLE
        elif b.bbox[1] < 200 and b.type is not BlockType.TITLE:
            b.type = BlockType.AUTHOR
