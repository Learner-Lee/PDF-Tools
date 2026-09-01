"""难词判定与生词本。"""
import pytest

from app.vocab.db import VOCAB_DB, VocabDB, get_vocab, tokenize
from app.vocab.difficulty import EXAM_ORDER, Profile, analyze

needs_db = pytest.mark.skipif(
    not VOCAB_DB.exists(),
    reason="需要词库：python -m scripts.fetch_wordlists && python -m scripts.build_vocab",
)


# ---------- 不依赖词库 ----------

def test_tokenize_keeps_offsets():
    """位置必须准确 —— 前端要靠它在原文上打标记。"""
    text = "The mitigation strategy proved efficacious."
    toks = tokenize(text)
    assert [t[2] for t in toks] == [
        "The", "mitigation", "strategy", "proved", "efficacious"]
    for start, end, word in toks:
        assert text[start:end] == word


def test_exam_levels_are_cumulative():
    assert Profile(exam_level="cet4").known_exams == {"zk", "gk", "cet4"}
    assert Profile(exam_level="gre").known_exams == set(EXAM_ORDER)


def test_missing_db_degrades_quietly(tmp_path):
    """词库没构建时不该抛错，让上层去提示用户。"""
    db = VocabDB(tmp_path / "nope.db")
    assert db.available is False
    assert analyze("some difficult vocabulary here", Profile(), db) == []


# ---------- 依赖词库 ----------

@pytest.fixture(scope="module")
def db():
    if not VOCAB_DB.exists():
        pytest.skip("需要词库：python -m scripts.fetch_wordlists && python -m scripts.build_vocab")
    return get_vocab()


@needs_db
def test_lemmatizes_irregular_forms(db):
    assert db.lemma("was") == "be"
    assert db.lemma("ran") == "run"
    assert db.lemma("analyses") == "analysis"
    assert db.lemma("mitigated") == "mitigate"


@needs_db
def test_higher_level_marks_fewer_words(db):
    text = (
        "Social media is an always-on setting for social comparison: users infer "
        "standing by comparing with others. Attention-optimizing feeds make ordinary "
        "posts implicit benchmarks, contributing to dissatisfaction, envy and rumination."
    )
    counts = [
        len(analyze(text, Profile(basis="coca", coca_tier=t), db))
        for t in (3000, 5000, 8000, 15000)
    ]
    assert counts == sorted(counts, reverse=True), counts

    exam_counts = [
        len(analyze(text, Profile(basis="exam", exam_level=lv), db))
        for lv in ("cet4", "cet6", "gre")
    ]
    assert exam_counts == sorted(exam_counts, reverse=True), exam_counts


@needs_db
def test_every_marked_word_has_a_gloss(db):
    """标了却点不出释义的词只会打断阅读，必须一个都没有。"""
    text = (
        "The lifestyle-oriented rankable self-evaluations were neutralized by "
        "idiosyncratic sycophancy and involution."
    )
    for w in analyze(text, Profile(basis="coca", coca_tier=5000), db):
        assert w.gloss.strip(), w.surface


@needs_db
def test_offsets_point_at_the_word(db):
    text = "Prompted classifiers exhibit neutralization of comparison-eliciting posts."
    for w in analyze(text, Profile(basis="coca", coca_tier=3000), db):
        assert text[w.start:w.end] == w.surface


@needs_db
def test_known_words_and_skip_list_are_respected(db):
    text = "This involution and rumination confound the analysis."
    base = {w.lemma for w in analyze(text, Profile(basis="coca", coca_tier=5000), db)}
    assert "involution" in base

    p = Profile(basis="coca", coca_tier=5000, known={"involution"})
    assert "involution" not in {w.lemma for w in analyze(text, p, db)}

    skipped = analyze(text, Profile(basis="coca", coca_tier=5000), db,
                      skip={"rumination"})
    assert "rumination" not in {w.lemma for w in skipped}


@needs_db
def test_same_word_marked_once_per_block(db):
    text = "Involution here, involution there, and involution everywhere."
    hits = [w for w in analyze(text, Profile(basis="coca", coca_tier=5000), db)
            if w.lemma == "involution"]
    assert len(hits) == 1
