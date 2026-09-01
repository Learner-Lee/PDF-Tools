"""生词本：收藏、导出。存在与翻译缓存同一个本地库里。"""
from __future__ import annotations

import csv
import io
import sqlite3
import threading

from ..config import CACHE_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vocab_book (
    lemma      TEXT PRIMARY KEY,
    surface    TEXT,
    phonetic   TEXT,
    pos        TEXT,
    gloss      TEXT,
    context    TEXT,          -- 收藏时所在的句子
    doc_id     TEXT,
    created_at REAL DEFAULT (strftime('%s','now'))
);
"""


class VocabBook:
    def __init__(self, path=CACHE_DB):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, item: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO vocab_book"
                " (lemma, surface, phonetic, pos, gloss, context, doc_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (item["lemma"], item.get("surface", ""), item.get("phonetic", ""),
                 item.get("pos", ""), item.get("gloss", ""),
                 item.get("context", ""), item.get("doc_id", "")),
            )
            self._conn.commit()

    def remove(self, lemma: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vocab_book WHERE lemma=?", (lemma,))
            self._conn.commit()

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM vocab_book ORDER BY created_at DESC")]

    def lemmas(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT lemma FROM vocab_book")}

    def export(self, fmt: str) -> tuple[str, str, str]:
        """返回 (文件名, MIME, 内容)。"""
        rows = self.list()
        if fmt == "anki":
            # Anki 的「基本」卡片：正面 制表符 背面，导入时选“字段由制表符分隔”
            body = "\n".join(
                "\t".join([
                    r["surface"] or r["lemma"],
                    " ".join(x for x in [
                        f"/{r['phonetic']}/" if r["phonetic"] else "",
                        r["gloss"] or "",
                        f"<br><i>{r['context']}</i>" if r["context"] else "",
                    ] if x),
                ]).replace("\n", " ")
                for r in rows
            )
            return "vocab-anki.txt", "text/plain; charset=utf-8", body
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["单词", "原形", "音标", "词性", "释义", "语境"])
        for r in rows:
            w.writerow([r["surface"], r["lemma"], r["phonetic"],
                        r["pos"], r["gloss"], r["context"]])
        return "vocab.csv", "text/csv; charset=utf-8", buf.getvalue()


_book: VocabBook | None = None


def get_book() -> VocabBook:
    global _book
    if _book is None:
        _book = VocabBook()
    return _book
