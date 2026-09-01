"""中文排版测量与字体。

字体不能用 `fontname="china-s"`：那条路径实际落到 Heiti，**拉丁字母是全角**，
"Cue-explicit" 十二个字母就占满 130pt，会被从词中间折断。学术译文里满是
XHS-SCoRE、GPT-5、LLM 这类拉丁词，必须用拉丁为比例宽度的字体。

`pymupdf.Font("china-s")` 解析出的是 Droid Sans Fallback（PyMuPDF 自带，
无需外部文件），拉丁部分是比例宽度。把它的字体缓冲嵌进输出 PDF 即可。

测量则利用 insert_textbox 的返回值恒等于「框高 − 实际所需高度」，
往足够高的框里试排一次就能得到精确高度，不必自己估算中英混排的换行。
"""
from __future__ import annotations

import pymupdf

FONT_ALIAS = "CJK"            # 页面内的字体别名
LINE_HEIGHT = 1.25            # 兜底行距；实际优先沿用原块的行距
_PROBE_HEIGHT = 5000.0

_font: pymupdf.Font | None = None
_scratch: pymupdf.Document | None = None
_scratch_page: pymupdf.Page | None = None


def cjk_font() -> pymupdf.Font:
    global _font
    if _font is None:
        _font = pymupdf.Font("china-s")
    return _font


def install_font(page: pymupdf.Page) -> None:
    """把中文字体注册到该页，之后才能用 FONT_ALIAS 写字。"""
    page.insert_font(fontname=FONT_ALIAS, fontbuffer=cjk_font().buffer)


def _page() -> pymupdf.Page:
    global _scratch, _scratch_page
    if _scratch_page is None:
        _scratch = pymupdf.open()
        _scratch_page = _scratch.new_page(width=1200, height=_PROBE_HEIGHT + 20)
        install_font(_scratch_page)
    return _scratch_page


def needed_height(
    text: str, width: float, fontsize: float, lineheight: float = LINE_HEIGHT
) -> float:
    """这段文字在给定宽度下需要的高度。"""
    if not text.strip() or width <= 2:
        return 0.0
    rc = _page().insert_textbox(
        pymupdf.Rect(0, 0, width, _PROBE_HEIGHT), text,
        fontname=FONT_ALIAS, fontsize=fontsize, lineheight=lineheight,
        render_mode=3,                       # 不可见，只为测量
    )
    return _PROBE_HEIGHT - rc


def fit_fontsize(
    text: str,
    width: float,
    available: float,
    preferred: float,
    lineheight: float = LINE_HEIGHT,
    min_ratio: float = 0.85,
    step: float = 0.5,
) -> tuple[float, float]:
    """在可用高度内挑一个字号。

    返回 (字号, 所需高度)。缩到下限仍放不下时返回下限字号 ——
    此时由排版层决定是往下推还是溢到下一页，绝不截断内容。
    """
    size = preferred
    floor = max(preferred * min_ratio, 5.0)
    while size >= floor:
        h = needed_height(text, width, size, lineheight)
        if h <= available:
            return size, h
        size -= step
    return floor, needed_height(text, width, floor, lineheight)


#: 拉丁单词的组成字符 —— 只有单词内部不能断，中文任意位置都可以
_WORDCHAR = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'"
)


def split_to_fit(
    text: str, width: float, fontsize: float, lineheight: float, available: float
) -> tuple[str, str]:
    """把文字切成「放得下的前半」与「剩下的后半」。

    原文横跨两页时，译文也应当流过同样的区域，而不是整段挤到一页去。
    二分找最长可容纳前缀，再回退到最近的标点或空格处断开，避免从词中间切。
    """
    if not text.strip() or available <= 0:
        return "", text
    if needed_height(text, width, fontsize, lineheight) <= available:
        return text, ""

    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if needed_height(text[:mid], width, fontsize, lineheight) <= available:
            lo = mid
        else:
            hi = mid - 1
    if lo <= 0:
        return "", text

    # 中文任意位置都可断；只有落在拉丁单词内部时才回退到词首，
    # 否则会切出 "XHS-S ‖ CoRE" 这种东西
    if lo < len(text) and text[lo - 1] in _WORDCHAR and text[lo] in _WORDCHAR:
        back = lo
        while back > 0 and text[back - 1] in _WORDCHAR:
            back -= 1
        if back > 0:
            lo = back
    return text[:lo].rstrip(), text[lo:].lstrip()
