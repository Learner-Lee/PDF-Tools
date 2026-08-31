"""文档接口：上传、取页、按需翻译。"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..services.documents import blocks_for_pages, get_documents, page_payload
from ..translator import ProviderError, Translator

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _summary(doc, filename: str = "") -> dict:
    total = sum(1 for b in doc.blocks() if b.translate)
    done = sum(1 for b in doc.blocks() if b.translate and b.translation)
    return {
        "id": doc.file_hash,
        "filename": filename,
        "page_count": doc.page_count,
        "is_text_pdf": doc.is_text_pdf,
        "title": (doc.meta or {}).get("title") or filename,
        "pages": [
            {"number": p.number, "width": p.width, "height": p.height, "columns": p.columns}
            for p in doc.pages
        ],
        "translatable": total,
        "translated": done,
    }


@router.get("")
def list_documents():
    return {"documents": get_documents().list()}


@router.post("")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "只支持 PDF 文件")
    store = get_documents()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        doc = store.ingest(tmp_path, file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not doc.is_text_pdf:
        # 扫描件需要 OCR，属于第二期
        raise HTTPException(
            422,
            "这是扫描版 PDF（没有可提取的文字层），当前版本只支持文字版 PDF。"
            "图片版需要先做 OCR，功能尚未上线。",
        )
    return _summary(doc, file.filename or "")


def _tables_for(doc, pages: set[int]):
    return [b for b in doc.blocks()
            if b.type.value == "table" and b.page in pages
            and not (b.table or {}).get("zh")]


def _need(doc_id: str):
    doc = get_documents().load(doc_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    return doc


@router.get("/{doc_id}")
def get_document(doc_id: str):
    return _summary(_need(doc_id))


@router.get("/{doc_id}/file")
def get_file(doc_id: str):
    path = get_documents().pdf_path(doc_id)
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type="application/pdf")


@router.get("/{doc_id}/pages")
def get_all_pages(doc_id: str):
    """一次取回全部页的块结构。不含 span，体量很小，省掉逐页往返。"""
    doc = _need(doc_id)
    return {"pages": [page_payload(doc, i) for i in range(doc.page_count)]}


@router.get("/{doc_id}/pages/{n}")
def get_page(doc_id: str, n: int):
    doc = _need(doc_id)
    if not 0 <= n < doc.page_count:
        raise HTTPException(404, "页码越界")
    return page_payload(doc, n)


class TranslateIn(BaseModel):
    pages: list[int]


@router.post("/{doc_id}/translate")
def translate_pages(doc_id: str, body: TranslateIn):
    """按页翻译（对照阅读的懒加载入口）。已译或已缓存的块不会重复调用 API。"""
    doc = _need(doc_id)
    todo = blocks_for_pages(doc, body.pages)
    tables = _tables_for(doc, set(body.pages))
    if not todo and not tables:
        return {"translations": {}, "tables": {}, "translated": 0, "from_cache": 0}
    try:
        tr = Translator()
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        tr.prepare_glossary(doc.file_hash, [b for b in doc.blocks() if b.translate])
        r = tr.translate_blocks(todo)
        if tables:
            rt = tr.translate_tables(tables)
            r.translated += rt.translated
            r.from_cache += rt.from_cache
    finally:
        tr.close()
    get_documents().persist(doc)
    return {
        "translations": {b.id: b.translation for b in todo if b.translation},
        "tables": {b.id: b.table for b in tables},
        "translated": r.translated,
        "from_cache": r.from_cache,
        "failed": r.failed,
    }


@router.post("/{doc_id}/translate-all")
async def translate_all(doc_id: str):
    """全文翻译，SSE 流式回报进度。与对照阅读共用同一份缓存。"""
    doc = _need(doc_id)
    try:
        tr = Translator()
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc

    todo = [b for b in doc.blocks() if b.translate and not b.translation]
    tables = _tables_for(doc, set(range(doc.page_count)))
    total = len(todo) + sum(len(t.table["rows"]) for t in tables)

    async def stream():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def work():
            try:
                tr.prepare_glossary(doc.file_hash, [b for b in doc.blocks() if b.translate])

                def on_progress(res):
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "progress", "done": res.translated + res.from_cache,
                         "total": total},
                    )

                res = tr.translate_blocks(todo, on_progress=on_progress)
                if tables:
                    rt = tr.translate_tables(tables)
                    res.translated += rt.translated
                    res.from_cache += rt.from_cache
                get_documents().persist(doc)
                loop.call_soon_threadsafe(queue.put_nowait, {
                    "type": "done", "translated": res.translated,
                    "from_cache": res.from_cache, "failed": res.failed,
                    "translations": {b.id: b.translation for b in todo if b.translation},
                    "tables": {b.id: b.table for b in tables},
                })
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "message": str(exc)}
                )
            finally:
                tr.close()
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, work)
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{doc_id}/retranslate")
def retranslate(doc_id: str):
    """清空已有译文，下次请求重新翻译。

    换了模型、或某段译得不对时的退路。命中缓存的部分不会重新花钱；
    要连缓存一起绕过，需在设置里换用别的模型。
    """
    doc = _need(doc_id)
    n = 0
    for b in doc.blocks():
        if b.translation:
            b.translation = None
            n += 1
        if b.table and b.table.pop("zh", None) is not None:
            n += 1
    get_documents().persist(doc)
    return {"ok": True, "cleared": n}


@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    get_documents().delete(doc_id)
    return {"ok": True}
