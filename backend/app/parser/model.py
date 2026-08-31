"""文档模型：解析层的输出，也是翻译层与渲染层的共同输入。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    TITLE = "title"                # 文档大标题
    AUTHOR = "author"              # 作者与单位
    HEADING = "heading"            # 章节标题
    BODY = "body"
    LIST = "list"
    CAPTION = "caption"            # 图表标题
    CODE = "code"                  # 等宽字体块
    MATH = "math"                  # 行间公式
    REFERENCE = "reference"        # 参考文献条目
    HEADER_FOOTER = "header_footer"
    WATERMARK = "watermark"        # arXiv 侧边戳等


#: 这些类型不送去翻译
NO_TRANSLATE = {
    BlockType.CODE,
    BlockType.MATH,
    BlockType.REFERENCE,       # 已确认：参考文献默认不翻译
    BlockType.HEADER_FOOTER,
    BlockType.WATERMARK,
}


@dataclass
class Span:
    text: str
    font: str
    size: float
    color: int
    bold: bool
    italic: bool
    mono: bool
    math: bool
    bbox: tuple[float, float, float, float]


@dataclass
class Block:
    id: str                        # "p3b07"，全文唯一，缓存与前端锚点都用它
    page: int                      # 0-based
    bbox: tuple[float, float, float, float]
    type: BlockType
    text: str
    spans: list[Span] = field(default_factory=list)
    column: int = 0                # 0=左栏 / 1=右栏 / -1=跨栏
    order: int = 0                 # 页内阅读顺序
    lang: str = "en"               # en | zh | mixed
    translate: bool = True
    merged_from: list[str] = field(default_factory=list)   # 作为段首，并入了哪些后续块
    merged_into: str | None = None                         # 作为续块，被并入了哪个段首
    translation: str | None = None

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class Image:
    bbox: tuple[float, float, float, float]
    xref: int


@dataclass
class Page:
    number: int
    width: float
    height: float
    columns: int = 1
    blocks: list[Block] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)


@dataclass
class Document:
    path: str
    file_hash: str
    page_count: int
    is_text_pdf: bool
    meta: dict[str, Any] = field(default_factory=dict)
    pages: list[Page] = field(default_factory=list)

    def blocks(self):
        for pg in self.pages:
            yield from pg.blocks

    def translatable(self) -> list[Block]:
        return [b for b in self.blocks() if b.translate and b.text.strip()]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Document":
        """从持久化的 JSON 还原。重启服务后不必重新解析 PDF。"""
        doc = Document(
            path=d["path"], file_hash=d["file_hash"], page_count=d["page_count"],
            is_text_pdf=d["is_text_pdf"], meta=d.get("meta") or {},
        )
        for pd in d.get("pages", []):
            pg = Page(
                number=pd["number"], width=pd["width"], height=pd["height"],
                columns=pd.get("columns", 1),
                images=[Image(bbox=tuple(i["bbox"]), xref=i.get("xref", 0))
                        for i in pd.get("images", [])],
            )
            for bd in pd.get("blocks", []):
                pg.blocks.append(Block(
                    id=bd["id"], page=bd["page"], bbox=tuple(bd["bbox"]),
                    type=BlockType(bd["type"]), text=bd["text"],
                    spans=[Span(**{**s, "bbox": tuple(s["bbox"])}) for s in bd.get("spans", [])],
                    column=bd.get("column", 0), order=bd.get("order", 0),
                    lang=bd.get("lang", "en"), translate=bd.get("translate", True),
                    merged_from=bd.get("merged_from") or [],
                    merged_into=bd.get("merged_into"),
                    translation=bd.get("translation"),
                ))
            doc.pages.append(pg)
        return doc

    def head_of(self, block: Block) -> Block:
        """取块所属的段首。跨块合并后，译文挂在段首上。"""
        if not block.merged_into:
            return block
        for b in self.blocks():
            if b.id == block.merged_into:
                return b
        return block
