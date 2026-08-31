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
