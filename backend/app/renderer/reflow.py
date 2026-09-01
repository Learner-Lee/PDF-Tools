"""版面回流：把译文放回原位，放不下往下推，仍放不下才溢到新页。

原则（DESIGN.md 第 2 节）：栏数、图片位置、标题层级保持不变，
允许变的只有文本块高度与总页数。绝不重叠、绝不截断。

两条关键约束：

1. 未被替换的块（公式、代码、表格、原本就是中文的段落）没有被抹掉，
   物理上仍在原地，所以和图片一样是**固定障碍**，译文必须绕开。
2. 段落合并后，段首块的 bbox 只是**第一行**的框。原段落真正占据的是
   它自己加上所有并入续块的区域 —— 而这些区域可能跨页。译文要按
   同一串区域依次流过去，原文横跨两页，译文也横跨两页。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..parser.model import Block, BlockType, Document, Page
from .measure import LINE_HEIGHT, fit_fontsize, needed_height, split_to_fit

MARGIN_TOP = 40.0
MARGIN_BOTTOM = 48.0
MIN_GAP = 3.0
OBSTACLE_GAP = 6.0

#: 保留原文、不参与回流，仅作为障碍
#: 正文首行缩进两格。原文这类模板用首行缩进而非行间距区分段落，
#: 译文不缩进就会连成一片，看着像同一段。
INDENT = "\u3000\u3000"

KEEP_AS_IS = {
    BlockType.MATH, BlockType.CODE, BlockType.TABLE,
    BlockType.HEADER_FOOTER, BlockType.WATERMARK,
}


@dataclass
class Slot:
    block_id: str
    page: int              # 源页号
    out_page: int          # 相对源页的第几页（0=原页）
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    fontsize: float
    lineheight: float = LINE_HEIGHT
    bold: bool = False


@dataclass
class PagePlan:
    source_page: int
    slots: list[Slot] = field(default_factory=list)
    redact: list[tuple[float, float, float, float]] = field(default_factory=list)
    extra_pages: int = 0


@dataclass
class _Region:
    """原段落占据的一段矩形区域。"""
    page: int
    column: int
    x0: float
    y0: float
    x1: float
    y1: float


def _base_size(b: Block, fallback: float) -> float:
    sizes = sorted(s.size for s in b.spans if s.text.strip())
    return sizes[len(sizes) // 2] if sizes else fallback


def _line_ratio(b: Block, fontsize: float) -> float:
    """沿用原块的行距。

    照搬一个「中文要更松」的固定值会把每段凭空撑高三成，
    原本更短的中文反而放不下、大面积溢页。原文行距才是这页的版面节奏。
    """
    tops = sorted({round(s.bbox[1], 1) for s in b.spans if s.text.strip()})
    if len(tops) < 2 or fontsize <= 0:
        return LINE_HEIGHT
    deltas = [t2 - t1 for t1, t2 in zip(tops, tops[1:]) if 0 < t2 - t1 < fontsize * 3]
    if not deltas:
        return LINE_HEIGHT
    return min(max(statistics.median(deltas) / fontsize, 1.15), 1.9)


def _is_bold(b: Block) -> bool:
    total = sum(len(s.text) for s in b.spans) or 1
    return sum(len(s.text) for s in b.spans if s.bold) / total > 0.6


def _regions(head: Block, by_id: dict[str, Block]) -> list[_Region]:
    """原段落占据的区域序列，按阅读顺序。同页同栏的合并成一块。"""
    parts = [head] + [by_id[i] for i in head.merged_from if i in by_id]
    parts.sort(key=lambda b: (b.page, b.column if b.column >= 0 else -1, b.order))
    out: list[_Region] = []
    for b in parts:
        x0, y0, x1, y1 = b.bbox
        if out and out[-1].page == b.page and out[-1].column == b.column:
            r = out[-1]
            r.x0, r.y0 = min(r.x0, x0), min(r.y0, y0)
            r.x1, r.y1 = max(r.x1, x1), max(r.y1, y1)
        else:
            out.append(_Region(b.page, b.column, x0, y0, x1, y1))
    return out


def _push_below_obstacles(top, height, x0, x1, obstacles) -> float:
    moved = True
    while moved:
        moved = False
        for ox0, oy0, ox1, oy1 in obstacles:
            if ox1 <= x0 + 1 or ox0 >= x1 - 1:
                continue
            if oy1 <= top or oy0 >= top + height:
                continue
            top = oy1 + OBSTACLE_GAP
            moved = True
    return top


def plan_document(
    doc: Document, translations: dict[str, str], body_size: float
) -> list[PagePlan]:
    plans = [PagePlan(source_page=p.number) for p in doc.pages]
    by_id = {b.id: b for b in doc.blocks()}
    pages: dict[int, Page] = {p.number: p for p in doc.pages}

    heads = [b for b in doc.blocks()
             if b.id in translations and not b.merged_into]
    heads.sort(key=lambda b: (b.page, b.order))

    # 先确定哪些块会被抹掉：段首及其并入的续块
    erased: set[str] = set()
    for h in heads:
        erased.add(h.id)
        erased.update(h.merged_from)

    # 凡是不会被抹掉的都是固定障碍 —— 它们物理上仍留在页上。
    # 尤其别漏掉「未翻译段首的续块」：它有 merged_into 却不会被抹，
    # 漏算就成了排版看不见的隐形文字，译文会直接压上去。
    obstacles: dict[int, list[tuple]] = {p.number: [] for p in doc.pages}
    for p in doc.pages:
        for b in p.blocks:
            if b.order >= 0 and b.id not in erased:
                obstacles[p.number].append(tuple(b.bbox))
        obstacles[p.number] += [tuple(i.bbox) for i in p.images]

    # 每（页, 栏）的排版游标，以及该栏当前写到第几张输出页
    cursor: dict[tuple[int, int], float] = {}
    prev_bottom: dict[tuple[int, int], float] = {}
    col_page: dict[tuple[int, int], int] = {}

    for head in heads:
        regions = _regions(head, by_id)
        size = _base_size(head, body_size)
        lh = _line_ratio(head, size)
        bold = _is_bold(head)
        rest = translations[head.id].strip()
        if head.type is BlockType.BODY:
            rest = INDENT + rest

        for b in [head] + [by_id[i] for i in head.merged_from if i in by_id]:
            plans[b.page].redact.append(tuple(b.bbox))

        for ri, reg in enumerate(regions):
            if not rest:
                break
            key = (reg.page, reg.column)
            page = pages[reg.page]
            bottom = page.height - MARGIN_BOTTOM
            width = max(reg.x1 - reg.x0, 20.0)
            on_extra = col_page.get(key, 0) > 0

            if key not in cursor:
                top = reg.y0
            elif on_extra:
                top = cursor[key] + MIN_GAP
            else:
                gap = max(reg.y0 - prev_bottom.get(key, reg.y0), MIN_GAP)
                top = cursor[key] + gap

            # 后续区域从原位开始即可，无需跟随本栏游标之后
            if ri > 0:
                top = max(top, reg.y0) if key in cursor else reg.y0

            fs, h = fit_fontsize(rest, width, max(bottom - top, 1.0), size, lh)
            if not on_extra:
                top = _push_below_obstacles(top, h, reg.x0, reg.x1, obstacles[reg.page])

            avail = bottom - top
            if h <= avail:
                chunk, rest = rest, ""
            elif ri + 1 < len(regions):
                # 还有后续区域，按原文的跨页方式分流
                fs = size
                chunk, rest = split_to_fit(rest, width, fs, lh, avail)
                if not chunk:                      # 这段区域一点也放不下
                    continue
                h = needed_height(chunk, width, fs, lh)
            else:
                # 最后一段区域仍放不下：开续页
                col_page[key] = col_page.get(key, 0) + 1
                plans[reg.page].extra_pages = max(
                    plans[reg.page].extra_pages, col_page[key]
                )
                top = MARGIN_TOP
                fs, h = fit_fontsize(rest, width, bottom - top, size, lh)
                chunk, rest = rest, ""

            plans[reg.page].slots.append(Slot(
                block_id=head.id, page=reg.page, out_page=col_page.get(key, 0),
                x0=reg.x0, y0=top, x1=reg.x1, y1=top + h,
                text=chunk, fontsize=fs, lineheight=lh, bold=bold,
            ))
            cursor[key] = top + h
            prev_bottom[key] = reg.y1

    return plans
