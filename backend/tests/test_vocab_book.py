"""生词本：收藏、去重、导出。"""
from app.vocab.book import VocabBook

WORD = {
    "lemma": "involution", "surface": "involution",
    "phonetic": ".invə'lu:ʃən", "pos": "n",
    "gloss": "n. 卷绕, 内卷, 回旋",
    "context": "In contemporary China, involution reframes comparison.",
}


def _book(tmp_path):
    return VocabBook(tmp_path / "book.db")


def test_add_and_list(tmp_path):
    b = _book(tmp_path)
    b.add(WORD)
    items = b.list()
    assert len(items) == 1
    assert items[0]["lemma"] == "involution"
    assert items[0]["context"].startswith("In contemporary China")


def test_adding_twice_does_not_duplicate(tmp_path):
    b = _book(tmp_path)
    b.add(WORD)
    b.add({**WORD, "gloss": "改过的释义"})
    assert len(b.list()) == 1
    assert b.list()[0]["gloss"] == "改过的释义"


def test_remove(tmp_path):
    b = _book(tmp_path)
    b.add(WORD)
    b.remove("involution")
    assert b.list() == []
    assert b.lemmas() == set()


def test_csv_export_has_header_and_row(tmp_path):
    b = _book(tmp_path)
    b.add(WORD)
    name, mime, body = b.export("csv")
    assert name.endswith(".csv") and "csv" in mime
    lines = body.strip().splitlines()
    assert lines[0].startswith("单词,原形,音标")
    assert "involution" in lines[1]


def test_anki_export_is_tab_separated_two_fields(tmp_path):
    b = _book(tmp_path)
    b.add(WORD)
    _, _, body = b.export("anki")
    line = body.strip().splitlines()[0]
    front, back = line.split("\t", 1)
    assert front == "involution"
    assert "内卷" in back
    assert "\t" not in back          # 背面不能再含制表符，否则字段会错位
