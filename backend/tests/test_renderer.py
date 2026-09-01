"""原版式导出：测量、断行、回流与渲染。"""
import pymupdf
import pytest

from app.parser.model import Block, BlockType, Page, Span
from app.renderer.measure import fit_fontsize, needed_height, split_to_fit
from app.renderer.reflow import _line_ratio, _push_below_obstacles

ZH = "中性化并非在方向上均匀分布。某些模型对原始向下项目的消除作用强于对原始向上项目。"


# ---------- 测量 ----------

def test_needed_height_grows_as_width_shrinks():
    wide = needed_height(ZH, 400, 10)
    narrow = needed_height(ZH, 150, 10)
    assert 0 < wide < narrow


def test_latin_words_are_not_full_width():
    """内置 china-s 会把拉丁字母排成全角，把 Cue-explicit 从词中间折断。

    嵌入的字体必须是比例宽度，否则中英混排的译文会处处溢出。
    """
    h = needed_height("B.5 Cue-explicit 提示", 120, 10.9, 1.25)
    assert h < 10.9 * 1.25 * 2          # 必须排得下一行


def test_fit_fontsize_shrinks_then_stops_at_floor():
    big, _ = fit_fontsize(ZH, 200, 500, 11)
    assert big == 11                     # 空间充足就不缩

    small, h = fit_fontsize(ZH, 200, 12, 11)
    assert small == pytest.approx(11 * 0.85, abs=0.6)   # 缩到下限就停
    assert h > 12                        # 仍放不下，交给排版层去推


# ---------- 断行 ----------

def test_split_keeps_everything():
    head, tail = split_to_fit(ZH, 200, 10, 1.25, 20)
    assert head and tail
    assert (head + tail).replace(" ", "") == ZH.replace(" ", "")


def test_split_does_not_cut_inside_latin_word():
    text = "我们提出了小红书社会比较读者诱发基准（XHS-SCoRE），这是一个以读者为中心的基准。"
    head, tail = split_to_fit(text, 220, 10, 1.25, 20)
    # 不能切成 "XHS-S" / "CoRE"
    assert not (head.rstrip().endswith(("S", "C", "o", "R", "E"))
                and tail.lstrip()[:1].isalpha())


def test_split_returns_all_when_it_fits():
    head, tail = split_to_fit(ZH, 400, 10, 1.25, 500)
    assert head == ZH and tail == ""


# ---------- 回流 ----------

def test_push_below_obstacles():
    obstacles = [(0, 100, 200, 160)]     # 横向覆盖 0~200，纵向 100~160
    assert _push_below_obstacles(90, 5, 0, 200, obstacles) == 90       # [90,95] 不相交
    assert _push_below_obstacles(90, 30, 0, 200, obstacles) > 160      # [90,120] 相交，被推下
    assert _push_below_obstacles(90, 50, 300, 400, obstacles) == 90    # 横向无关，不动


def test_line_ratio_follows_the_original():
    """行距要沿用原块。照搬一个固定值会把每段凭空撑高，导致大面积溢页。"""
    spans = [
        Span(text="x", font="F", size=10, color=0, bold=False, italic=False,
             mono=False, math=False, bbox=(0, y, 100, y + 10))
        for y in (0, 12, 24, 36)
    ]
    b = Block(id="b", page=0, bbox=(0, 0, 100, 46), type=BlockType.BODY,
              text="x", spans=spans)
    assert _line_ratio(b, 10) == pytest.approx(1.2, abs=0.05)


def test_line_ratio_has_a_floor():
    """原文行距过紧时也不能低于下限，中文字面比西文满。"""
    spans = [
        Span(text="x", font="F", size=10, color=0, bold=False, italic=False,
             mono=False, math=False, bbox=(0, y, 100, y + 10))
        for y in (0, 10, 20)
    ]
    b = Block(id="b", page=0, bbox=(0, 0, 100, 30), type=BlockType.BODY,
              text="x", spans=spans)
    assert _line_ratio(b, 10) >= 1.15
