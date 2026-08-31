"""把翻译缓存从一个 provider 标识迁到另一个。

缓存键含 provider 标识，端点地址变了（或早期版本用的是别的标识）会让
已付费的译文变成孤儿。本工具按源文本重算键，原地迁移，不重新调用 API。

    python -m scripts.remap_cache --list
    python -m scripts.remap_cache --from qwen --to api.example.com/v1
    python -m scripts.remap_cache --from qwen --to-active
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import CACHE_DB          # noqa: E402
from app.translator.cache import TranslationCache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(CACHE_DB))
    ap.add_argument("--list", action="store_true", help="列出各 provider 的条目数")
    ap.add_argument("--from", dest="src", help="源 provider 标识")
    ap.add_argument("--to", dest="dst", help="目标 provider 标识")
    ap.add_argument("--to-active", action="store_true", help="目标取当前启用档案的端点")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row

    if a.list or not a.src:
        print("缓存条目分布：")
        for r in conn.execute(
            "SELECT provider, model, COUNT(*) n FROM translations GROUP BY provider, model"
        ):
            print(f"  {r['provider']:<45} {r['model']:<18} {r['n']} 条")
        return 0

    dst = a.dst
    if a.to_active:
        from app.translator import get_provider

        p = get_provider()
        dst = p.cache_id
        p.close()
    if not dst:
        print("需要 --to 或 --to-active", file=sys.stderr)
        return 2

    rows = conn.execute(
        "SELECT * FROM translations WHERE provider=?", (a.src,)
    ).fetchall()
    if not rows:
        print(f"没有 provider={a.src!r} 的条目")
        return 0

    moved = skipped = 0
    for r in rows:
        new_key = TranslationCache.key(r["source"], r["lang"], dst, r["model"])
        exists = conn.execute(
            "SELECT 1 FROM translations WHERE key=?", (new_key,)
        ).fetchone()
        if exists:
            skipped += 1
            continue
        if not a.dry_run:
            conn.execute(
                "INSERT INTO translations"
                " (key,text_hash,lang,provider,model,source,result)"
                " VALUES (?,?,?,?,?,?,?)",
                (new_key, r["text_hash"], r["lang"], dst, r["model"],
                 r["source"], r["result"]),
            )
        moved += 1

    if not a.dry_run:
        conn.commit()
    print(f"{'将迁移' if a.dry_run else '已迁移'} {moved} 条到 {dst!r}"
          f"{f'，跳过已存在 {skipped} 条' if skipped else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
