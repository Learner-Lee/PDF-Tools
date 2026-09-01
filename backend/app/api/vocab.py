"""难词接口：等级设置、逐页取难词、生词本。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.documents import get_documents
from ..translator.cache import TranslationCache
from ..translator.glossary import proper_nouns
from ..store import get_store
from ..vocab import (
    COCA_TIERS,
    EXAM_LABELS,
    EXAM_ORDER,
    Profile,
    analyze,
    get_book,
    get_vocab,
)

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

_PROFILE_KEY = "vocab_profile"


def load_profile() -> Profile:
    return Profile.from_dict(get_store().get_setting(_PROFILE_KEY, None))


class ProfileIn(BaseModel):
    basis: str = "coca"
    coca_tier: int = 5000
    exam_level: str = "cet6"


@router.get("/profile")
def get_profile():
    db = get_vocab()
    p = load_profile()
    return {
        "profile": p.to_dict(),
        "available": db.available,
        "coca_tiers": COCA_TIERS,
        "exams": [{"key": k, "label": EXAM_LABELS[k]} for k in EXAM_ORDER],
        "hint": (
            "" if db.available else
            "词库尚未构建。在项目根目录运行："
            "python -m scripts.fetch_wordlists 然后 python -m scripts.build_vocab"
        ),
    }


@router.put("/profile")
def put_profile(body: ProfileIn):
    if body.basis not in ("coca", "exam"):
        raise HTTPException(400, "basis 只能是 coca 或 exam")
    p = load_profile()
    p.basis, p.coca_tier, p.exam_level = body.basis, body.coca_tier, body.exam_level
    get_store().set_setting(_PROFILE_KEY, p.to_dict())
    return p.to_dict()


class HardWordsIn(BaseModel):
    pages: list[int] = Field(default_factory=list)


@router.post("/documents/{doc_id}/hardwords")
def hard_words(doc_id: str, body: HardWordsIn):
    """按页取难词。全程离线，不调用任何 API。"""
    db = get_vocab()
    if not db.available:
        raise HTTPException(
            503,
            "词库尚未构建。请运行 python -m scripts.fetch_wordlists "
            "与 python -m scripts.build_vocab。",
        )
    doc = get_documents().load(doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")

    profile = load_profile()
    # 只跳过用户明确标记为"已掌握"的词。收藏进生词本恰恰说明还在学，
    # 若一并跳过，收藏之后这个词就再也不高亮了，与学习意图相反。
    profile.known |= set(get_store().get_setting("vocab_known", []) or [])

    # 专有名词不该当难词：作者名、机构名、模型名会被词库里的同名缩写乱配释义
    skip = {t.lower() for t in TranslationCache().get_glossary(doc.file_hash)}
    skip |= proper_nouns([b.text for b in doc.blocks() if b.lang != "zh"])

    want = set(body.pages)
    out: dict[str, list[dict]] = {}
    for b in doc.blocks():
        if b.page not in want or b.merged_into or b.lang == "zh":
            continue
        # 作者与单位块是姓名和机构，不是阅读材料
        if b.type.value in ("header_footer", "watermark", "math", "code",
                            "table", "author"):
            continue
        found = analyze(b.text, profile, db, skip=skip)
        if found:
            out[b.id] = [asdict(w) for w in found]
    return {"hardwords": out, "profile": profile.to_dict()}


class BookIn(BaseModel):
    lemma: str
    surface: str = ""
    phonetic: str = ""
    pos: str = ""
    gloss: str = ""
    context: str = ""
    doc_id: str = ""


@router.get("/book")
def list_book():
    return {"items": get_book().list()}


@router.post("/book")
def add_book(body: BookIn):
    get_book().add(body.model_dump())
    return {"ok": True, "count": len(get_book().list())}


@router.delete("/book/{lemma}")
def remove_book(lemma: str):
    get_book().remove(lemma)
    return {"ok": True}


@router.get("/book/export")
def export_book(format: str = "csv"):
    if format not in ("csv", "anki"):
        raise HTTPException(400, "format 只能是 csv 或 anki")
    name, mime, body = get_book().export(format)
    return Response(
        content=body.encode("utf-8-sig" if format == "csv" else "utf-8"),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
