"""解析入口：PDF 文件 -> Document 模型。"""
from __future__ import annotations

import hashlib
import statistics
from pathlib import Path

import pymupdf

from . import classify as _cls
from . import layout as _lay
from .extract import (
    collect_hyphen_vocab,
    collect_words,
    detect_lang,
    extract_blocks,
    join_lines,
)
from .merge import merge_paragraphs
from .model import NO_TRANSLATE, Block, BlockType, Document, Image, Page
from .tables import find_tables

#: 解析逻辑变更时递增。已持久化的文档模型据此失效并重新解析，
#: 否则用户升级后仍会看到旧解析结果（如附录被误判为参考文献）。
PARSER_VERSION = 3

#: 平均每页可提取字符数低于此值，判定为扫描件，需 OCR（第一版不支持）
TEXT_PDF_MIN_CHARS_PER_PAGE = 100


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _overlap_ratio(inner: tuple, outer: tuple) -> float:
    """inner 有多大比例落在 outer 内。

    不能用完全包含判定：PyMuPDF 的文本块常比表格的横线范围略大
    （末行字母的下伸部会越过底线），实测因此漏掉整张表。
    """
    w = min(inner[2], outer[2]) - max(inner[0], outer[0])
    h = min(inner[3], outer[3]) - max(inner[1], outer[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return (w * h) / area if area > 0 else 0.0


def _body_size(doc: pymupdf.Document) -> float:
    """全文最常见的字号，作为正文基准。"""
    sizes: list[float] = []
    for pg in doc:
        for blk in pg.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    sizes.extend([round(sp["size"], 1)] * len(sp["text"]))
    if not sizes:
        return 10.0
    try:
        return statistics.mode(sizes)
    except statistics.StatisticsError:
        return statistics.median(sizes)


def parse(path: str | Path) -> Document:
    path = str(path)
    src = pymupdf.open(path)

    total_chars = sum(len(pg.get_text().strip()) for pg in src)
    is_text = total_chars / max(src.page_count, 1) >= TEXT_PDF_MIN_CHARS_PER_PAGE

    doc = Document(
        path=path,
        file_hash=file_hash(path),
        page_count=src.page_count,
        is_text_pdf=is_text,
        meta={**dict(src.metadata or {}), "parser_version": PARSER_VERSION},
    )
    if not is_text:
        return doc      # 扫描件：调用方据此提示用户，OCR 留到第二期

    body_size = _body_size(src)
    in_refs = False
    global_order: list[Block] = []

    # 先把所有页的行抽出来，再建连字符词表 —— 判断行尾 "-" 是断词还是复合词，
    # 需要以整篇文档为证据，所以抽取与拼接必须分两趟。
    raw_pages = [extract_blocks(pg) for pg in src]
    all_lines = [ln for pg in raw_pages for (_, _, lines) in pg for ln in lines]
    hyphen_vocab = collect_hyphen_vocab(all_lines)
    words = collect_words(all_lines)

    for pno, src_page in enumerate(src):
        pw, ph = src_page.rect.width, src_page.rect.height
        page = Page(number=pno, width=pw, height=ph)

        for info in src_page.get_image_info(xrefs=True):
            page.images.append(Image(bbox=tuple(info["bbox"]), xref=info.get("xref", 0)))

        for i, (bbox, spans, lines) in enumerate(raw_pages[pno]):
            text = join_lines(lines, hyphen_vocab, words)
            if not text.strip():
                continue
            page.blocks.append(
                Block(
                    id=f"p{pno}b{i:02d}",
                    page=pno,
                    bbox=bbox,
                    type=BlockType.BODY,     # 占位，随即分类
                    text=text,
                    spans=spans,
                    lang=detect_lang(text),
                )
            )

        # 表格：整块替换掉区域内的散落文本块，否则同样内容会重复出现
        for ti, tbl in enumerate(find_tables(src_page, hyphen_vocab, words)):
            inside = [
                b for b in page.blocks if _overlap_ratio(b.bbox, tbl.bbox) >= 0.6
            ]
            if not inside:
                continue
            # 表格块的框取横线范围与实际文本范围的并集，左栏高亮才对得准
            bbox = (
                min([tbl.bbox[0]] + [b.bbox[0] for b in inside]),
                min([tbl.bbox[1]] + [b.bbox[1] for b in inside]),
                max([tbl.bbox[2]] + [b.bbox[2] for b in inside]),
                max([tbl.bbox[3]] + [b.bbox[3] for b in inside]),
            )
            for b in inside:
                page.blocks.remove(b)
            page.blocks.append(
                Block(
                    id=f"p{pno}t{ti}",
                    page=pno,
                    bbox=bbox,
                    type=BlockType.TABLE,
                    text=" ".join(c for r in tbl.rows for c in r if c),
                    spans=[],
                    lang="en",
                    table={"rows": tbl.rows, "header_rows": tbl.header_rows},
                )
            )

        in_refs = _cls.classify_page(page.blocks, ph, pw, body_size, in_refs)
        if pno == 0:
            _cls.mark_front_matter(page.blocks)

        page.columns = _lay.detect_columns(page.blocks, pw)
        _lay.assign_columns(page.blocks, pw, page.columns)
        ordered = _lay.reading_order(page.blocks, page.columns)

        for b in page.blocks:
            # 中文块已经是目标语言，再翻一遍只会得到垃圾
            # 表格走单元格级翻译，不作为整段文本送去
            b.translate = (
                b.type not in NO_TRANSLATE
                and b.type is not BlockType.TABLE
                and b.lang != "zh"
            )

        global_order.extend(ordered)
        doc.pages.append(page)

    merge_paragraphs(global_order, hyphen_vocab, words)
    src.close()
    return doc
