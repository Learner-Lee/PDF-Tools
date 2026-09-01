"""把下载的原始词表编译成应用使用的紧凑词库。

原始 ecdict.csv 有 66MB / 77 万条，其中大量是词组与生僻变体。
这里只留单词形态且有中文释义的条目，按查询需要重排字段，
并把 COCA 词频序、考试标签、词形还原表一并并进同一个库。

    python -m scripts.build_vocab
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "wordlists" / "raw"
OUT = ROOT / "data" / "vocab.db"

csv.field_size_limit(10**7)

#: 只收单词形态：字母开头，允许连字符与撇号
RE_WORD = re.compile(r"^[a-zA-Z][a-zA-Z'-]{0,30}$")

SCHEMA = """
PRAGMA journal_mode = OFF;
DROP TABLE IF EXISTS words;
DROP TABLE IF EXISTS lemma;
CREATE TABLE words (
    word        TEXT PRIMARY KEY,   -- 一律小写
    phonetic    TEXT,
    pos         TEXT,
    tag         TEXT,               -- 空格分隔：cet4 cet6 ky toefl ielts gre gk zk
    collins     INTEGER,            -- 柯林斯星级 0~5
    oxford      INTEGER,            -- 是否牛津三千核心词
    bnc         INTEGER,            -- BNC 词频序，0 表示未收录
    frq         INTEGER,            -- 当代语料词频序
    coca        INTEGER,            -- COCA 前两万的名次，0 表示在两万以外
    translation TEXT
);
CREATE TABLE lemma (
    variant TEXT PRIMARY KEY,       -- 变形（小写）
    lemma   TEXT NOT NULL           -- 原形
);
"""


def _unescape(v: str | None) -> str:
    """ECDICT 的 CSV 把换行写成字面的两字符 \\n，还原成真换行。

    不还原的话，按行拆分释义（去掉 [医]、[计] 这类学科标注）会完全失效。
    """
    return (v or "").replace("\\n", "\n").replace("\\r", "").strip()


def _int(v: str | None) -> int:
    v = (v or "").strip()
    return int(v) if v.isdigit() else 0


def load_coca() -> dict[str, int]:
    """COCA 前两万的名次。行号即名次。"""
    path = RAW / "coca20000.txt"
    if not path.exists():
        print("  ! 缺少 coca20000.txt，将只依赖 ECDICT 词频")
        return {}
    ranks: dict[str, int] = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            w = line.strip().lower()
            if w and w not in ranks:
                ranks[w] = i
    return ranks


def load_lemma() -> dict[str, str]:
    """变形 -> 原形。lemma.en.txt 的格式是 `原形/词频 -> 变形,变形,...`"""
    path = RAW / "lemma.en.txt"
    if not path.exists():
        print("  ! 缺少 lemma.en.txt，词形还原将退化为规则法")
        return {}
    out: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or "->" not in line:
                continue
            head, variants = line.split("->", 1)
            lemma = head.split("/")[0].strip().lower()
            if not lemma:
                continue
            for v in variants.split(","):
                v = v.strip().lower()
                # 变形指向自身没有意义；已有映射不覆盖（文件按词频降序，先到的更常用）
                if v and v != lemma and v not in out:
                    out[v] = lemma
    return out


def main() -> int:
    src = RAW / "ecdict.csv"
    if not src.exists():
        print(f"找不到 {src}\n请先运行：python -m scripts.fetch_wordlists", file=sys.stderr)
        return 1

    coca = load_coca()
    lemma = load_lemma()
    print(f"COCA 词频序 {len(coca):,} 条 | 词形还原 {len(lemma):,} 条")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    conn = sqlite3.connect(OUT)
    conn.executescript(SCHEMA)

    rows = []
    kept = skipped = 0
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            w = (r.get("word") or "").strip()
            if not RE_WORD.match(w):
                skipped += 1
                continue
            tr = _unescape(r.get("translation"))
            if not tr:
                skipped += 1
                continue
            lw = w.lower()
            rows.append((
                lw,
                (r.get("phonetic") or "").strip(),
                _unescape(r.get("pos")),
                (r.get("tag") or "").strip(),
                _int(r.get("collins")),
                _int(r.get("oxford")),
                _int(r.get("bnc")),
                _int(r.get("frq")),
                coca.get(lw, 0),
                tr,
            ))
            kept += 1
            if len(rows) >= 20000:
                conn.executemany(
                    "INSERT OR IGNORE INTO words VALUES (?,?,?,?,?,?,?,?,?,?)", rows
                )
                rows.clear()
    if rows:
        conn.executemany("INSERT OR IGNORE INTO words VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    conn.executemany(
        "INSERT OR IGNORE INTO lemma VALUES (?,?)", list(lemma.items())
    )
    conn.execute("CREATE INDEX idx_words_coca ON words(coca) WHERE coca > 0")
    conn.execute("CREATE INDEX idx_words_tag  ON words(tag)  WHERE tag <> ''")
    conn.commit()

    n_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    n_lemma = conn.execute("SELECT COUNT(*) FROM lemma").fetchone()[0]
    n_coca = conn.execute("SELECT COUNT(*) FROM words WHERE coca > 0").fetchone()[0]
    n_ph = conn.execute("SELECT COUNT(*) FROM words WHERE phonetic <> ''").fetchone()[0]
    conn.execute("VACUUM")
    conn.close()

    print(f"\n收录 {n_words:,} 词（跳过词组与无释义条目 {skipped:,}）")
    print(f"  其中有 COCA 名次 {n_coca:,}，有音标 {n_ph:,}")
    print(f"  词形还原 {n_lemma:,} 条")
    print(f"\n输出 {OUT}  ({OUT.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
