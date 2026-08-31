"""表格识别：以真实论文为准，兼顾"识别不准时要能退回文本"。"""
from pathlib import Path

import pymupdf
import pytest

from app.parser.tables import Table, find_tables

SAMPLE = Path(__file__).resolve().parents[2] / "2605.01017v2-8.pdf"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="需要样本 PDF")


@pytest.fixture(scope="module")
def doc():
    d = pymupdf.open(SAMPLE)
    yield d
    d.close()


def test_finds_the_real_tables(doc):
    """5 张真表格全部识别；正文不得被误切成表格。"""
    found = {p: find_tables(doc[p]) for p in range(doc.page_count)}
    pages = {p for p, ts in found.items() if ts}
    assert pages == {2, 4, 5, 12}          # 0-based：p3 p5 p6 p13
    assert sum(len(ts) for ts in found.values()) == 5


def test_main_results_table_is_exact(doc):
    """p5 的主结果表：8x8，表头与数值必须一字不差。"""
    t = find_tables(doc[4])[0]
    assert (len(t.rows), t.col_count) == (8, 8)
    assert t.rows[0] == [
        "Model", "Type", "Acc", "Macro-F1",
        "Rec UP", "Rec NEU", "Rec DOWN", "Pred (as) NEU",
    ]
    assert t.rows[1][:4] == ["GPT-5", "LLM", "0.521", "0.518"]
    assert t.rows[-1][:2] == ["CN-MacBERT Base", "Encoder"]


def test_adjacent_tables_are_not_merged(doc):
    """同页上下相邻的两张表必须分开 —— 横线端点差几 pt 就会被并成一张。"""
    tables = find_tables(doc[5])
    assert len(tables) == 1                # 另一张是嵌套表，按下面的规则被剔除
    assert tables[0].rows[0][0] == "Condition"


def test_hyphenated_label_keeps_hyphen(doc):
    """折行的复合词标签要还原成 Persona-primed，而不是 Personaprimed。"""
    from app.parser.extract import collect_hyphen_vocab, collect_words, extract_blocks

    lines = [l for pg in doc for (_, _, ls) in extract_blocks(pg) for l in ls]
    t = [x for x in find_tables(doc[12], collect_hyphen_vocab(lines), collect_words(lines))
         if x.col_count == 4][0]
    assert "Persona-primed" in [r[0] for r in t.rows]


def test_garbled_table_is_rejected():
    """一格里挤进多个数值说明列没切开，宁可退回文本也不摆错表。"""
    good = Table(bbox=(0, 0, 1, 1), rows=[["Model", "F1"], ["GPT-5", "51.8"]])
    bad = Table(bbox=(0, 0, 1, 1),
                rows=[["Model", "F1"], ["GPT-5", "51.8 46.9 55.8"]])
    assert good.is_meaningful()
    assert not bad.is_meaningful()


def test_sparse_table_is_rejected():
    sparse = Table(bbox=(0, 0, 1, 1),
                   rows=[["a", "", ""], ["", "", ""], ["", "b", ""]])
    assert not sparse.is_meaningful()
