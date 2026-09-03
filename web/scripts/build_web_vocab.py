"""把本地版的 39MB 词库压成浏览器可下载的精简版。

只保留「有词频名次或考试标签」的词条 —— 这些是难词判定真正会用到的。
更生僻的词查不到释义时不做标记（给不出释义的下划线只会打断阅读），
所以不必把 40 万条全带上。

    python3 scripts/build_web_vocab.py

输入：<repo>/data/vocab.db（由 backend/scripts/build_vocab.py 生成）
输出：web/public/vocab.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "vocab.db"
OUT = Path(__file__).resolve().parents[1] / "public" / "vocab.json"

#: 释义裁到这个长度。卡片显示够用，再长只是徒增体积。
MAX_GLOSS = 60


def main() -> int:
    if not SRC.exists():
        print(f"找不到 {SRC}\n请先在仓库根目录跑：\n"
              "  cd backend && ../.venv/bin/python -m scripts.fetch_wordlists\n"
              "  cd backend && ../.venv/bin/python -m scripts.build_vocab",
              file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    words: dict[str, list] = {}
    rows = conn.execute(
        "SELECT word, phonetic, pos, tag, coca, frq, translation FROM words"
        " WHERE coca > 0 OR tag <> '' OR frq > 0"
    )
    for r in rows:
        gloss = brief(r["translation"])
        if not gloss:
            continue
        # 紧凑数组而非对象：省掉几万份重复的键名，体积差一倍
        words[r["word"]] = [
            r["phonetic"] or "", r["pos"] or "", r["tag"] or "",
            r["coca"] or 0, gloss[:MAX_GLOSS],
        ]

    # 词形还原表只保留指向已收录词的条目
    lemma = {
        v: l for v, l in conn.execute("SELECT variant, lemma FROM lemma")
        if l in words
    }
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"words": words, "lemma": lemma}, ensure_ascii=False,
                   separators=(",", ":")),
        encoding="utf-8",
    )
    size = OUT.stat().st_size / 1048576
    print(f"收录 {len(words):,} 词，词形还原 {len(lemma):,} 条")
    print(f"输出 {OUT}  ({size:.1f} MB，gzip 后约 {size * 0.35:.1f} MB)")
    return 0


_FIELD_TAG_PREFIX = "["


def brief(translation: str | None) -> str:
    """取前两条释义，去掉学科标注前缀。"""
    raw = [l.strip() for l in (translation or "").split("\n") if l.strip()]
    plain = [l for l in raw if not l.startswith(_FIELD_TAG_PREFIX)]
    use = plain or [strip_tag(l) for l in raw]
    return "；".join(use[:2])


def strip_tag(line: str) -> str:
    if line.startswith("[") and "]" in line:
        return line.split("]", 1)[1].strip()
    return line


if __name__ == "__main__":
    raise SystemExit(main())
