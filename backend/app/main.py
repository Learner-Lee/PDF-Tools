"""PDF Tools 本地服务入口。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import documents, settings as settings_api

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="PDF Tools", version="0.1.0")

# 本地应用，前端开发服务器与后端不同端口，放开跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(settings_api.router)


@app.get("/api/health")
def health():
    from .store import get_store

    active = get_store().active()
    return {
        "ok": True,
        "provider_configured": active is not None and bool(active.api_key or active.base_url),
        "active_provider": active.label if active else None,
    }


# 前端构建产物存在时一并托管，单端口即可使用
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if f.is_file() else _DIST / "index.html")
