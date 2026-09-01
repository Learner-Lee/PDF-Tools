"""生成保留原版式的中文 PDF。

以原页为底：抹掉要替换的文字层（图片与矢量图完整保留），
再把译文按回流结果放回去。未翻译的内容（公式、代码、表格、
原本就是中文的段落、页码）原样留在页上。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..parser.model import Document
from .measure import FONT_ALIAS, install_font
from .reflow import PagePlan, Slot, plan_document

#: 模拟粗体的描边宽度（该字体没有粗体变体）。
#: 相对字号取值，0.28 会把中文字形糊成黑块，0.05 才是清晰的粗体。
_BOLD_STROKE = 0.05


@dataclass
class RenderReport:
    pages_in: int = 0
    pages_out: int = 0
    blocks_placed: int = 0
    shrunk: int = 0                  # 缩过字号的块
    spilled_pages: int = 0           # 因放不下而新增的页
    warnings: list[str] = field(default_factory=list)


def _body_size(doc: Document) -> float:
    sizes = [s.size for b in doc.blocks() for s in b.spans if s.text.strip()]
    return statistics.median(sizes) if sizes else 10.0


def _draw(page: pymupdf.Page, slot: Slot) -> bool:
    rect = pymupdf.Rect(slot.x0, slot.y0, slot.x1, slot.y1 + 2)
    kw = dict(
        fontname=FONT_ALIAS, fontsize=slot.fontsize,
        lineheight=slot.lineheight, align=pymupdf.TEXT_ALIGN_LEFT,
    )
    if slot.bold:
        # 内置中文字体无粗体变体，用描边加粗，保住标题与正文的层级关系
        kw.update(render_mode=2, border_width=_BOLD_STROKE)
    return page.insert_textbox(rect, slot.text, **kw) >= 0


def render_pdf(doc: Document, out_path: str | Path) -> RenderReport:
    """把已翻译的文档渲染成中文 PDF。"""
    report = RenderReport(pages_in=doc.page_count)
    src = pymupdf.open(doc.path)

    # 译文按块 id 索引；表格与保留原文的块不在其中
    # 译文与原文一字不差时不替换：抹掉再画一遍相同内容只有风险没有收益
    # （模型名、纯数字的表格碎片本就不该翻）
    translations = {
        b.id: b.translation for b in doc.blocks()
        if b.translation and b.translation.strip()
        and b.translation.strip() != b.text.strip()
        and not b.merged_into
    }
    body = _body_size(doc)

    plans: list[PagePlan] = plan_document(doc, translations, body)

    # 从后往前处理，插入续页不会打乱前面页的下标
    for page in reversed(doc.pages):
        plan = plans[page.number]

        if plan.redact:
            target = src[page.number]
            for r in plan.redact:
                target.add_redact_annot(pymupdf.Rect(r))
            target.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )

        # 续页紧跟在本页之后，保持阅读顺序
        for i in range(plan.extra_pages):
            src.new_page(pno=page.number + 1 + i,
                         width=page.width, height=page.height)
        report.spilled_pages += plan.extra_pages

        # 插页会重建页树，之前取的 Page 引用全部失效，必须重新取
        for i in range(plan.extra_pages + 1):
            if plan.slots:
                install_font(src[page.number + i])

        for slot in plan.slots:
            dest = src[page.number + slot.out_page]
            if not _draw(dest, slot):
                report.warnings.append(f"{slot.block_id} 未能完全放入")
            report.blocks_placed += 1

    report.pages_out = src.page_count
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src.save(str(out_path), garbage=3, deflate=True)
    src.close()
    return report
