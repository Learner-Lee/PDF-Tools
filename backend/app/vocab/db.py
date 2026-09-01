"""词库访问：词形还原、词条查询。

数据由 scripts/fetch_wordlists.py + scripts/build_vocab.py 生成，不入库。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT

VOCAB_DB = ROOT / "data" / "vocab.db"

#: ECDICT 的音标用旧式记号，统一成 IPA 常见写法
_PHONETIC_FIX = str.maketrans({"ә": "ə", "ɔ": "ɔ", "ʃ": "ʃ", "ɑ": "ɑ"})

_RE_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*")
#: 释义里的学科标注，如 "[医] "、"[计] "
_RE_FIELD_TAG = re.compile(r"^\[[^\]]{1,6}\]\s*")


@dataclass
class Entry:
    word: str
    phonetic: str = ""
    pos: str = ""
    tag: str = ""
    collins: int = 0
    oxford: int = 0
    bnc: int = 0
    frq: int = 0
    coca: int = 0
    translation: str = ""

    @property
    def tags(self) -> set[str]:
        return set(self.tag.split())

    def gloss(self, limit: int = 3) -> str:
        """取前几条释义。

        优先用不带学科标注的行；整条都只有 "[医]自我评价" 这类时也要能用，
        所以退而求其次时把标注前缀去掉再返回。
        """
        raw = [l.strip() for l in (self.translation or "").split("\n") if l.strip()]
        plain = [l for l in raw if not l.startswith("[")]
        if plain:
            return "；".join(plain[:limit])
        return "；".join(_RE_FIELD_TAG.sub("", l).strip() for l in raw[:limit])


class VocabDB:
    """只读词库。缺库时所有查询返回空，调用方据此提示用户去构建。"""

    def __init__(self, path: Path = VOCAB_DB):
        self.path = path
        self.available = path.exists()
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if self.available:
            self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

    # ---------- 词形还原 ----------

    def lemma(self, token: str) -> str:
        """变形还原为原形。查表优先，查不到再退回规则。"""
        w = token.lower().strip("'-")
        if not w:
            return ""
        if self._conn is not None:
            with self._lock:
                r = self._conn.execute(
                    "SELECT lemma FROM lemma WHERE variant=?", (w,)
                ).fetchone()
            if r:
                return r["lemma"]
            if self.has(w):
                return w
        return _rule_lemma(w)

    def has(self, word: str) -> bool:
        if self._conn is None:
            return False
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM words WHERE word=?", (word.lower(),)
            ).fetchone() is not None

    # ---------- 词条 ----------

    def get(self, word: str) -> Entry | None:
        if self._conn is None:
            return None
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM words WHERE word=?", (word.lower(),)
            ).fetchone()
        if not r:
            return None
        return Entry(
            word=r["word"],
            phonetic=(r["phonetic"] or "").translate(_PHONETIC_FIX),
            pos=r["pos"] or "", tag=r["tag"] or "",
            collins=r["collins"], oxford=r["oxford"],
            bnc=r["bnc"], frq=r["frq"], coca=r["coca"],
            translation=r["translation"] or "",
        )

    def get_many(self, words: list[str]) -> dict[str, Entry]:
        out: dict[str, Entry] = {}
        for w in dict.fromkeys(x.lower() for x in words):
            e = self.get(w)
            if e:
                out[w] = e
        return out

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()


def _rule_lemma(w: str) -> str:
    """词表查不到时的兜底规则。只处理最常见的规则变化。"""
    for suf, repl in (
        ("ies", "y"), ("ied", "y"), ("ying", "ie"),
        ("sses", "ss"), ("shes", "sh"), ("ches", "ch"), ("xes", "x"),
        ("ing", ""), ("ed", ""), ("es", ""), ("s", ""),
    ):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: len(w) - len(suf)] + repl
    return w


def tokenize(text: str) -> list[tuple[int, int, str]]:
    """切出英文词，返回 (起点, 终点, 原词)。位置用于前端在原文上打标记。"""
    return [(m.start(), m.end(), m.group(0)) for m in _RE_TOKEN.finditer(text)]


_db: VocabDB | None = None


def get_vocab() -> VocabDB:
    global _db
    if _db is None:
        _db = VocabDB()
    return _db
