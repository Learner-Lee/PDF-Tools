"""栏检测与阅读顺序重建。

双栏论文里，PyMuPDF 的原始块序碰巧常常是对的，但不可依赖 —— 一旦顺序错乱，
译文会整篇错位。这里显式重建：先识别跨栏块（标题、宽表），用它们把页面切成
若干横向条带，条带内再按 左栏自上而下 → 右栏自上而下 排序。
"""
from __future__ import annotations

from .model import Block

#: 跨栏判定容差（pt）：块必须实质性越过中缝才算跨栏
_STRADDLE_TOL = 12.0


def detect_columns(blocks: list[Block], page_width: float) -> int:
    """判断页面是单栏还是双栏。"""
    body = [b for b in blocks if b.type.value not in ("header_footer", "watermark")]
    if len(body) < 4:
        return 1
    mid = page_width / 2
    left = [b for b in body if b.bbox[2] <= mid + _STRADDLE_TOL]
    right = [b for b in body if b.bbox[0] >= mid - _STRADDLE_TOL]
    straddle = [b for b in body if b not in left and b not in right]

    # 用文本量而非块数量判断：论文首页天然有一串跨栏块（标题、作者、单位、
    # 邮箱），按块数会把双栏首页误判成单栏，进而让右栏内容排到左栏前面。
    # 但这些块字数都很少，按文本量衡量就压不过双栏正文。
    if len(left) >= 2 and len(right) >= 2:
        col_chars = sum(len(b.text) for b in left + right)
        straddle_chars = sum(len(b.text) for b in straddle)
        if col_chars > straddle_chars:
            return 2
    return 1


def assign_columns(blocks: list[Block], page_width: float, columns: int) -> None:
    """就地写入每个块的 column：0=左 1=右 -1=跨栏。"""
    if columns == 1:
        for b in blocks:
            b.column = 0
        return
    mid = page_width / 2
    for b in blocks:
        x0, _, x1, _ = b.bbox
        if x1 <= mid + _STRADDLE_TOL:
            b.column = 0
        elif x0 >= mid - _STRADDLE_TOL:
            b.column = 1
        else:
            b.column = -1


def reading_order(blocks: list[Block], columns: int) -> list[Block]:
    """返回按阅读顺序排列的块，并就地写入 order。"""
    content = [b for b in blocks if b.type.value not in ("header_footer", "watermark")]
    skipped = [b for b in blocks if b not in content]

    if columns == 1:
        ordered = sorted(content, key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    else:
        straddle = sorted([b for b in content if b.column == -1], key=lambda b: b.bbox[1])
        colblocks = [b for b in content if b.column != -1]

        # 跨栏块把页面切成条带：每个跨栏块之前的双栏内容自成一带
        ordered: list[Block] = []
        top = 0.0
        for s in straddle + [None]:
            bound = s.bbox[1] if s is not None else float("inf")
            band = [b for b in colblocks if top <= b.bbox[1] < bound]
            for col in (0, 1):
                ordered.extend(
                    sorted(
                        (b for b in band if b.column == col),
                        key=lambda b: (round(b.bbox[1], 1), b.bbox[0]),
                    )
                )
            if s is not None:
                ordered.append(s)
                top = s.bbox[3]

        # 兜底：任何因浮点边界漏掉的块按位置补回，绝不丢内容
        missing = [b for b in colblocks if b not in ordered]
        ordered.extend(sorted(missing, key=lambda b: (b.column, b.bbox[1])))

    for i, b in enumerate(ordered):
        b.order = i
    for b in skipped:
        b.order = -1
    return ordered
