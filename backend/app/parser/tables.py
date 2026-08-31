"""表格识别。

PyMuPDF 自带的 find_tables 对学术论文常用的 booktabs 表格不可用：
"lines" 策略要求完整网格（这类表格只有横线），"text" 策略会把正常的
双栏正文切成大量假表格（实测把 19 页论文切出 19 个 57x8 的"表"）。

这里按 booktabs 的实际结构来还原：一组 x 范围相同的横线界定一张表，
首尾横线之间的文本按 y 聚成行、按 x 区间合并成列，第一条中线以上为表头。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

from .extract import line_text, make_span, stitch_hyphen

#: 横线判定：足够细、足够长
_RULE_MAX_H = 3.0
_RULE_MIN_W = 40.0
#: 同一张表的横线，左右端点差异不超过此值（pt）。
#: 必须收得很紧：同一张表的横线由 LaTeX 一次性画出，端点完全一致；
#: 放宽到 12pt 会把同页上下相邻的两张表并成一张。
_RULE_X_TOL = 2.5
#: 行聚类的 y 容差
_ROW_TOL = 3.0
#: 一个格子里出现这么多个独立数值，说明列切分失真
_GARBLED_NUMS = 3

_RE_NUM = re.compile(r"(?<![\w.])[-−–]?\d+(?:[.,]\d+)?%?(?![\w])")


@dataclass
class Table:
    bbox: tuple[float, float, float, float]
    rows: list[list[str]] = field(default_factory=list)
    header_rows: int = 1

    @property
    def col_count(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def is_meaningful(self) -> bool:
        """至少 2 行 2 列，且格子不能太空。

        识别失真时宁可退回普通文本块，也不要在界面上摆一张千疮百孔的表。
        """
        if len(self.rows) < 2 or self.col_count < 2:
            return False
        total = len(self.rows) * self.col_count
        filled = sum(1 for r in self.rows for c in r if c.strip())
        if filled / total < 0.5:
            return False
        # 数值表里一格塞进多个数，是列切分没切开的信号。
        # 与其摆一张错位的表误导阅读，不如退回普通文本块。
        for row in self.rows[self.header_rows:]:
            for cell in row:
                if len(_RE_NUM.findall(cell)) >= _GARBLED_NUMS:
                    return False
        return True


def _rules(page: pymupdf.Page) -> list[pymupdf.Rect]:
    out = []
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.height <= _RULE_MAX_H and r.width >= _RULE_MIN_W:
            out.append(r)
    return sorted(out, key=lambda r: (round(r.y0, 1), r.x0))


def _group_rules(rules: list[pymupdf.Rect]) -> list[list[pymupdf.Rect]]:
    """按左右端点把横线分组，每组对应一张表。"""
    groups: list[list[pymupdf.Rect]] = []
    for r in rules:
        for g in groups:
            if (
                abs(g[0].x0 - r.x0) <= _RULE_X_TOL
                and abs(g[0].x1 - r.x1) <= _RULE_X_TOL
            ):
                g.append(r)
                break
        else:
            groups.append([r])
    return [g for g in groups if len(g) >= 2]     # 至少上下两条线才算表


def _cells_in(page: pymupdf.Page, box: tuple) -> list[tuple[float, float, float, str]]:
    """区域内的单元格：(y, x0, x1, text)。行内按空隙切分。"""
    x0, top, x1, bot = box
    out = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            lx0, ly0, lx1, ly1 = ln["bbox"]
            if not (top - 2 <= ly0 and ly1 <= bot + 2 and lx0 >= x0 - 6 and lx1 <= x1 + 6):
                continue
            spans = [make_span(s) for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            group, cur = [], [spans[0]]
            for s in spans[1:]:
                # 间隙超过约一个字宽即视为跨到下一格
                if s.bbox[0] - cur[-1].bbox[2] > 0.9 * max(s.size, 1.0):
                    group.append(cur)
                    cur = [s]
                else:
                    cur.append(s)
            group.append(cur)
            for cell in group:
                text = line_text(cell).strip()
                if text:
                    out.append((ly0, cell[0].bbox[0], cell[-1].bbox[2], text))
    return out


def _columns(cells: list[tuple[float, float, float, str]]) -> list[tuple[float, float]]:
    """把所有单元格的 x 区间合并成列。

    表头常左对齐、数据常居中，同一列的 x 区间并不相等但必然重叠；
    不同列之间则有干净的空隙。合并重叠区间即可得到列边界。
    """
    spans = sorted((c[1], c[2]) for c in cells)
    cols: list[list[float]] = []
    for a, b in spans:
        if cols and a <= cols[-1][1]:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    return [(a, b) for a, b in cols]


def _build(cells, cols, mid_y: float | None,
           hyphen_vocab: set[str], words: set[str]) -> Table:
    rows_by_y: list[tuple[float, list]] = []
    for y, cx0, cx1, text in sorted(cells):
        if rows_by_y and abs(rows_by_y[-1][0] - y) <= _ROW_TOL:
            rows_by_y[-1][1].append((cx0, cx1, text))
        else:
            rows_by_y.append((y, [(cx0, cx1, text)]))

    grid: list[list[str]] = []
    for _, items in rows_by_y:
        row = [""] * len(cols)
        for cx0, cx1, text in items:
            # 落到重叠最多的那一列
            best, best_ov = 0, -1.0
            for i, (a, b) in enumerate(cols):
                ov = min(cx1, b) - max(cx0, a)
                if ov > best_ov:
                    best_ov, best = ov, i
            row[best] = (row[best] + " " + text).strip() if row[best] else text
        grid.append(row)

    header = 1
    if mid_y is not None:
        header = max(1, sum(1 for y, _ in rows_by_y if y < mid_y))
    # booktabs 表格几乎不会有超过两行表头，多出来必是识别偏了
    header = min(header, 2, max(len(grid) - 1, 1))

    grid, header = _merge_wrapped(grid, header, hyphen_vocab, words)
    return Table(bbox=(0, 0, 0, 0), rows=grid, header_rows=header)


def _merge_wrapped(
    grid: list[list[str]], header: int,
    hyphen_vocab: set[str], words: set[str],
) -> tuple[list[list[str]], int]:
    """把换行续写的行并回上一行。

    单元格内容过长时会折行，折出来的那一行首列为空 —— 若不合并，
    一张 4 行的表会变成 16 行，每行支离破碎。
    """
    out: list[list[str]] = []
    new_header = header
    for i, row in enumerate(grid):
        # 首列自身也可能折行（"Persona-" / "primed"），以连字符结尾即是续写
        head_wrapped = bool(out) and out[-1][0].rstrip().endswith("-")
        is_cont = (
            out
            and (not row[0].strip() or head_wrapped)
            and any(c.strip() for c in row)
            and i >= header          # 表头自身的多行结构要保留
        )
        if is_cont:
            for j, cell in enumerate(row):
                if not cell.strip():
                    continue
                prev = out[-1][j]
                if not prev:
                    out[-1][j] = cell
                elif prev.rstrip().endswith("-"):
                    # 复用正文那套连字符消歧：Persona-primed 要留连字符，
                    # rea-/der 要接成一个词。判据只应有一份。
                    out[-1][j] = stitch_hyphen(
                        prev.rstrip(), cell.lstrip(), hyphen_vocab, words
                    )
                else:
                    out[-1][j] = prev + " " + cell
        else:
            out.append(list(row))
            if i < header:
                new_header = len(out)
    return out, min(new_header, max(len(out) - 1, 1))


def find_tables(
    page: pymupdf.Page,
    hyphen_vocab: set[str] | None = None,
    words: set[str] | None = None,
) -> list[Table]:
    hyphen_vocab = hyphen_vocab or set()
    words = words or set()
    out: list[Table] = []
    for group in _group_rules(_rules(page)):
        group.sort(key=lambda r: r.y0)
        top, bot = group[0].y0, group[-1].y1
        x0 = min(r.x0 for r in group)
        x1 = max(r.x1 for r in group)
        cells = _cells_in(page, (x0, top, x1, bot))
        if len(cells) < 4:
            continue
        cols = _columns(cells)
        if len(cols) < 2:
            continue
        # 第二条横线通常是表头分隔线
        mid = group[1].y0 if len(group) >= 3 else None
        t = _build(cells, cols, mid, hyphen_vocab, words)
        t.bbox = (x0, top, x1, bot)
        if t.is_meaningful():
            out.append(t)
    return out
