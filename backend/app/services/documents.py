"""文档服务：上传、解析、持久化、按页取块。

解析结果持久化成 JSON，重启后不必重新解析；同一份 PDF（按内容 hash）
再次上传直接复用，连解析都省掉。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from pathlib import Path

from ..config import CACHE_DB, STORAGE
from ..parser import parse
from ..parser.pipeline import PARSER_VERSION
from ..parser.model import Block, Document, apply_translate_policy
from ..store import get_store

UPLOADS = STORAGE / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    file_hash  TEXT PRIMARY KEY,
    filename   TEXT,
    page_count INTEGER,
    model_json TEXT,
    created_at REAL DEFAULT (strftime('%s','now'))
);
"""


class DocumentStore:
    def __init__(self, path=CACHE_DB):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._mem: dict[str, Document] = {}

    # ---------- 写入 ----------

    def ingest(self, src: Path, filename: str) -> Document:
        """保存上传文件并解析。内容相同的 PDF 直接复用已有结果。"""
        from ..parser.pipeline import file_hash

        h = file_hash(src)
        dest = UPLOADS / f"{h}.pdf"
        if not dest.exists():
            shutil.copyfile(src, dest)

        existing = self.load(h)
        if existing is not None:
            return existing


        doc = parse(dest)
        self._save(h, filename, doc)
        self._mem[h] = doc
        apply_translate_policy(doc, self.translate_references())
        return doc

    def _save(self, h: str, filename: str, doc: Document) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents (file_hash, filename, page_count, model_json)"
                " VALUES (?,?,?,?)",
                (h, filename, doc.page_count, json.dumps(doc.to_dict(), ensure_ascii=False)),
            )
            self._conn.commit()

    def persist(self, doc: Document) -> None:
        """翻译结果写回文档模型，避免重启后丢失已译内容。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT filename FROM documents WHERE file_hash=?", (doc.file_hash,)
            ).fetchone()
        self._save(doc.file_hash, row["filename"] if row else "", doc)

    # ---------- 读取 ----------

    def load(self, h: str) -> Document | None:
        if h in self._mem:
            # 设置可能已改，每次取用都按当前策略重算
            apply_translate_policy(self._mem[h], self.translate_references())
            return self._mem[h]
        with self._lock:
            row = self._conn.execute(
                "SELECT model_json, filename FROM documents WHERE file_hash=?", (h,)
            ).fetchone()
        if not row:
            return None
        doc = Document.from_dict(json.loads(row["model_json"]))
        # 解析器升级后旧模型作废，否则会一直沿用过时的解析结果
        if (doc.meta or {}).get("parser_version") != PARSER_VERSION:
            pdf = self.pdf_path(h)
            if not pdf.exists():
                return None
            doc = parse(pdf)
            self._save(h, row["filename"] if "filename" in row.keys() else "", doc)
        self._mem[h] = doc
        apply_translate_policy(doc, self.translate_references())
        return doc

    @staticmethod
    def translate_references() -> bool:
        return bool(get_store().get_setting("translate_references", False))

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT file_hash, filename, page_count, created_at"
                " FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, h: str) -> None:
        self._mem.pop(h, None)
        (UPLOADS / f"{h}.pdf").unlink(missing_ok=True)
        with self._lock:
            self._conn.execute("DELETE FROM documents WHERE file_hash=?", (h,))
            self._conn.commit()

    @staticmethod
    def pdf_path(h: str) -> Path:
        return UPLOADS / f"{h}.pdf"


_store: DocumentStore | None = None


def get_documents() -> DocumentStore:
    global _store
    if _store is None:
        _store = DocumentStore()
    return _store


# ---------- 视图辅助 ----------


def page_payload(doc: Document, n: int) -> dict:
    """一页的渲染数据。

    段落跨块合并后，译文挂在段首块上，而段首可能在上一页甚至上一栏。
    这里给每个块都带上 head_id，前端据此把左栏的高亮框与右栏的译文段对应起来。
    """
    pg = doc.pages[n]
    heads = {b.id for b in doc.blocks() if not b.merged_into}
    blocks = []
    for b in sorted(pg.blocks, key=lambda x: (x.order < 0, x.order)):
        blocks.append({
            "id": b.id,
            "head_id": b.merged_into or b.id,
            "is_head": b.id in heads,
            "type": b.type.value,
            "bbox": list(b.bbox),
            "column": b.column,
            "order": b.order,
            "lang": b.lang,
            "translate": b.translate,
            "text": b.text,
            "translation": b.translation,
            "table": b.table,
        })
    return {
        "page": n,
        "width": pg.width,
        "height": pg.height,
        "columns": pg.columns,
        "images": [{"bbox": list(i.bbox)} for i in pg.images],
        "blocks": blocks,
    }


def blocks_for_pages(doc: Document, pages: list[int]) -> list[Block]:
    """这些页需要翻译的块（解析到段首，去重，保持阅读顺序）。"""
    want = set(pages)
    seen: set[str] = set()
    out: list[Block] = []
    for pg in doc.pages:
        for b in pg.blocks:
            if b.page not in want:
                continue
            head = doc.head_of(b)
            if head.id in seen or not head.translate or head.translation:
                continue
            seen.add(head.id)
            out.append(head)
    return out
