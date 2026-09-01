"""Markdown 保底导出。

原版式重建再稳也可能在某些文档上失真，所以每次导出都无条件附一份
Markdown：丢掉版式但内容完整、可二次编辑，永远不会「什么都拿不到」。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..parser.model import Block, BlockType, Document

#: 章节标题的层级：按编号点数推断，"4.4 xxx" 是三级
_RE_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+\S")


def _heading_level(text: str) -> int:
    m = _RE_NUM.match(text)
    if not m:
        return 2
    return min(2 + m.group(1).count("."), 6)


def _table_md(table: dict) -> str:
    rows = table.get("zh") or table.get("rows") or []
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    head = table.get("header_rows", 1) or 1

    def line(cells):
        cells = list(cells) + [""] * (ncol - len(cells))
        return "| " + " | ".join(c.replace("|", "\\|").strip() for c in cells) + " |"

    out = [line(r) for r in rows[:head]]
    out.append("|" + "|".join([" --- "] * ncol) + "|")
    out += [line(r) for r in rows[head:]]
    return "\n".join(out)


def _render_block(b: Block) -> str:
    text = (b.translation or b.text).strip()
    if b.type is BlockType.TABLE:
        return _table_md(b.table or {})
    if not text:
        return ""
    if b.type is BlockType.TITLE:
        return f"# {text}"
    if b.type is BlockType.HEADING:
        return f"{'#' * _heading_level(text)} {text}"
    if b.type in (BlockType.CODE, BlockType.MATH):
        return f"```\n{b.text.strip()}\n```"
    if b.type is BlockType.CAPTION:
        return f"*{text}*"
    if b.type is BlockType.AUTHOR:
        return f"*{text}*"
    if b.type is BlockType.REFERENCE:
        return f"- {text}"
    if b.type is BlockType.LIST:
        return text if text[:1] in "-*•" else f"- {text.lstrip('•· ')}"
    return text


def render_markdown(doc: Document, out_path: str | Path) -> Path:
    lines: list[str] = []
    title = (doc.meta or {}).get("title") or Path(doc.path).stem
    lines.append(f"<!-- 由 PDF 对照导出：{title} -->\n")

    prev_ref = False
    for page in doc.pages:
        for b in sorted(
            [x for x in page.blocks if x.order >= 0 and not x.merged_into],
            key=lambda x: x.order,
        ):
            if b.type in (BlockType.HEADER_FOOTER, BlockType.WATERMARK):
                continue
            md = _render_block(b)
            if not md:
                continue
            # 连续的参考文献条目之间不空行，成组呈现
            if not (prev_ref and b.type is BlockType.REFERENCE) and lines:
                lines.append("")
            lines.append(md)
            prev_ref = b.type is BlockType.REFERENCE

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return out_path
