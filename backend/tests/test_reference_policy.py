"""参考文献：条目合并与"是否翻译"的运行时策略。"""
from pathlib import Path

import pytest

from app.parser import parse
from app.parser.model import BlockType, apply_translate_policy

SAMPLE = Path(__file__).resolve().parents[2] / "2605.01017v2-8.pdf"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="需要样本 PDF")


@pytest.fixture(scope="module")
def doc():
    return parse(SAMPLE)


def _heads(doc):
    return [b for b in doc.blocks()
            if b.type is BlockType.REFERENCE and not b.merged_into]


def test_hanging_indent_entries_are_merged(doc):
    """悬挂缩进的续行要并回条目首行，否则作者与标题会被分开翻译。"""
    refs = [b for b in doc.blocks() if b.type is BlockType.REFERENCE]
    heads = _heads(doc)
    assert len(heads) < len(refs)          # 确有合并发生
    assert any(b.merged_from for b in heads)

    first = heads[0].text
    assert first.startswith("Helmut Appel")
    assert "2016." in first                # 年份来自续行，说明接上了


def test_policy_toggles_without_reparsing(doc):
    """开关要能对已解析的文档立即生效。"""
    apply_translate_policy(doc, translate_references=False)
    off = len(doc.translatable())

    apply_translate_policy(doc, translate_references=True)
    on = len(doc.translatable())
    assert on - off == len(_heads(doc))     # 只多出文献条目，不多不少

    apply_translate_policy(doc, translate_references=False)
    assert len(doc.translatable()) == off


def test_merged_children_never_translated(doc):
    """并入条目的续行块不能再单独翻译，否则内容重复。"""
    apply_translate_policy(doc, translate_references=True)
    assert all(not b.translate for b in doc.blocks() if b.merged_into)


def test_chinese_references_stay_untranslated(doc):
    apply_translate_policy(doc, translate_references=True)
    assert all(not b.translate for b in doc.blocks() if b.lang == "zh")
