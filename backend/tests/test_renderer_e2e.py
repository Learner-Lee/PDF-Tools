"""端到端导出：以真实论文为准。"""
from pathlib import Path

import pymupdf
import pytest

from app.parser import parse
from app.renderer import render_markdown, render_pdf

SAMPLE = Path(__file__).resolve().parents[2] / "2605.01017v2-8.pdf"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="需要样本 PDF")


@pytest.fixture(scope="module")
def doc():
    d = parse(SAMPLE)
    # 用可辨认的假译文，避免依赖翻译缓存
    for i, b in enumerate(d.translatable()):
        b.translation = f"译文{i}：" + "中文内容测试。" * max(1, len(b.text) // 60)
    return d


def test_pdf_keeps_images_and_line_art(doc, tmp_path):
    """抹字必须保图：表格横线与插图不能被一起抹掉。"""
    src = pymupdf.open(SAMPLE)
    before_draw = sum(len(p.get_drawings()) for p in src)
    before_img = sum(len(p.get_images()) for p in src)

    out = tmp_path / "zh.pdf"
    render_pdf(doc, out)
    res = pymupdf.open(out)

    assert sum(len(p.get_drawings()) for p in res) >= before_draw
    assert sum(len(p.get_images()) for p in res) >= before_img


def test_pdf_page_count_stays_reasonable(doc, tmp_path):
    """中文比英文短，页数不该膨胀。失控的溢页说明排版参数错了。"""
    r = render_pdf(doc, tmp_path / "zh.pdf")
    assert r.pages_out >= r.pages_in
    assert r.pages_out <= r.pages_in * 1.8, f"{r.pages_in} -> {r.pages_out}"


def test_pdf_text_is_extractable(doc, tmp_path):
    """输出必须仍可搜索复制，不能是图片。"""
    out = tmp_path / "zh.pdf"
    render_pdf(doc, out)
    text = "".join(p.get_text() for p in pymupdf.open(out))
    assert "中文内容测试" in text


def test_no_translated_block_is_left_undrawn(doc, tmp_path):
    r = render_pdf(doc, tmp_path / "zh.pdf")
    assert r.blocks_placed > 0
    assert not r.warnings, r.warnings[:3]


def test_untranslated_content_is_not_erased(doc, tmp_path):
    """公式、代码、原本就是中文的段落要原样留在页上。"""
    out = tmp_path / "zh.pdf"
    render_pdf(doc, out)
    text = "".join(p.get_text() for p in pymupdf.open(out))
    assert "eduhk.hk" in text                     # 邮箱（等宽块）
    assert "小红书" in text                        # 论文自带的中文示例


def test_markdown_fallback_has_structure(doc, tmp_path):
    out = render_markdown(doc, tmp_path / "zh.md")
    md = out.read_text(encoding="utf-8")
    assert md.startswith("<!--")
    assert "\n# " in md or md.startswith("# ")   # 标题
    assert "| --- " in md                         # 表格
    assert "译文0" in md
