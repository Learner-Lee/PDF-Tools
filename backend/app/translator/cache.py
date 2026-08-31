"""翻译缓存。

键取源文本的 hash 而非块 id：解析逻辑一旦改动、块 id 或切分方式变化，
旧结果会自动失效；反之全文重复出现的段落只需翻译一次。
对照阅读与全文导出共用这一张表 —— 看过的页不会再花第二次钱。
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

from ..config import CACHE_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    key         TEXT PRIMARY KEY,
    text_hash   TEXT NOT NULL,
    lang        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    source      TEXT NOT NULL,
    result      TEXT NOT NULL,
    created_at  REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_text_hash ON translations(text_hash);

CREATE TABLE IF NOT EXISTS glossary (
    doc_hash   TEXT NOT NULL,
    term       TEXT NOT NULL,
    rendering  TEXT NOT NULL,
    PRIMARY KEY (doc_hash, term)
);

CREATE TABLE IF NOT EXISTS documents (
    file_hash  TEXT PRIMARY KEY,
    filename   TEXT,
    page_count INTEGER,
    model_json TEXT,
    created_at REAL DEFAULT (strftime('%s','now'))
);
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class TranslationCache:
    def __init__(self, path: Path | str = CACHE_DB):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def key(text: str, lang: str, provider: str, model: str) -> str:
        return f"{_hash(text)}:{lang}:{provider}:{model}"

    def get_many(
        self, texts: list[str], lang: str, provider: str, model: str
    ) -> dict[str, str]:
        """按源文本批量取缓存，返回 {源文本: 译文}。"""
        if not texts:
            return {}
        keys = {self.key(t, lang, provider, model): t for t in texts}
        out: dict[str, str] = {}
        with self._lock:
            for chunk_start in range(0, len(keys), 500):
                chunk = list(keys)[chunk_start : chunk_start + 500]
                q = ",".join("?" * len(chunk))
                for k, res in self._conn.execute(
                    f"SELECT key, result FROM translations WHERE key IN ({q})", chunk
                ):
                    out[keys[k]] = res
        return out

    def put_many(
        self, pairs: list[tuple[str, str]], lang: str, provider: str, model: str
    ) -> None:
        if not pairs:
            return
        rows = [
            (self.key(src, lang, provider, model), _hash(src), lang, provider, model, src, dst)
            for src, dst in pairs
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO translations"
                " (key, text_hash, lang, provider, model, source, result)"
                " VALUES (?,?,?,?,?,?,?)",
                rows,
            )
            self._conn.commit()

    def get_glossary(self, doc_hash: str) -> dict[str, str]:
        with self._lock:
            return dict(
                self._conn.execute(
                    "SELECT term, rendering FROM glossary WHERE doc_hash=?", (doc_hash,)
                )
            )

    def put_glossary(self, doc_hash: str, mapping: dict[str, str]) -> None:
        if not mapping:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO glossary (doc_hash, term, rendering) VALUES (?,?,?)",
                [(doc_hash, t, r) for t, r in mapping.items()],
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
            g = self._conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
        return {"translations": n, "glossary": g}

    def close(self) -> None:
        self._conn.close()
