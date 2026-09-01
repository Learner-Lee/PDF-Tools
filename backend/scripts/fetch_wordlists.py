"""下载难词功能所需的公开词表。

数据源（均为可自由使用的公开数据）：

| 文件 | 来源 | 许可 | 用途 |
|---|---|---|---|
| ecdict.csv | skywind3000/ECDICT | MIT | 中文释义、音标、词性、考试标签、BNC/当代词频 |
| lemma.en.txt | skywind3000/ECDICT | MIT | 词形还原（BNC 语料生成，免去 spaCy 依赖） |
| coca20000.txt | mahavivo/english-wordlists | 公开整理 | COCA 前两万词频序，用于「我认识前 N 千词」档位 |

    python -m scripts.fetch_wordlists          # 下载缺失的
    python -m scripts.fetch_wordlists --force  # 全部重新下载
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "wordlists" / "raw"

SOURCES = {
    "ecdict.csv": "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
    "lemma.en.txt": "https://raw.githubusercontent.com/skywind3000/ECDICT/master/lemma.en.txt",
    "coca20000.txt": (
        "https://raw.githubusercontent.com/mahavivo/english-wordlists/master/COCA_20000.txt"
    ),
}


def fetch(name: str, url: str, force: bool) -> None:
    dest = RAW / name
    if dest.exists() and not force:
        print(f"  已存在，跳过  {name}  ({dest.stat().st_size / 1048576:.1f} MB)")
        return
    print(f"  下载中        {name} …", end="", flush=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    print(f" 完成 ({dest.stat().st_size / 1048576:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(f"目标目录：{RAW}")
    for name, url in SOURCES.items():
        fetch(name, url, a.force)
    print("\n接着运行：python -m scripts.build_vocab")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
