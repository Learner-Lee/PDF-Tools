"""设置接口：Provider 档案的增删改查、模型列表、连通性自检。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..presets import PRESETS
from ..store import ProviderProfile, get_store
from ..translator import ProviderError, from_profile, probe

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProfileIn(BaseModel):
    id: str = ""
    label: str = "未命名"
    base_url: str = ""
    #: 留空表示"不改动"，因为前端回显的是遮蔽值，原样提交不能覆盖真实密钥
    api_key: str = ""
    model_translate: str = ""
    model_gloss: str = ""
    extra_body: dict = Field(default_factory=dict)

    def to_profile(self) -> ProviderProfile:
        return ProviderProfile(**self.model_dump())


class OptionsIn(BaseModel):
    translate_references: bool


@router.get("/options")
def get_options():
    store = get_store()
    return {"translate_references": bool(store.get_setting("translate_references", False))}


@router.put("/options")
def put_options(body: OptionsIn):
    get_store().set_setting("translate_references", body.translate_references)
    return {"translate_references": body.translate_references}


@router.get("/presets")
def list_presets():
    return {"presets": PRESETS}


@router.get("/providers")
def list_providers():
    store = get_store()
    return {
        "providers": [p.masked() for p in store.list()],
        "active": store.active_id(),
    }


@router.put("/providers")
def upsert_provider(body: ProfileIn):
    if not body.base_url:
        raise HTTPException(400, "base_url 不能为空")
    p = get_store().upsert(body.to_profile())
    return p.masked()


@router.delete("/providers/{pid}")
def delete_provider(pid: str):
    get_store().delete(pid)
    return {"ok": True, "active": get_store().active_id()}


@router.post("/providers/{pid}/activate")
def activate_provider(pid: str):
    store = get_store()
    if store.get(pid) is None:
        raise HTTPException(404, "档案不存在")
    store.set_active(pid)
    return {"ok": True, "active": pid}


def _resolve(body: ProfileIn) -> ProviderProfile:
    """未填密钥时沿用已存档案的密钥，让"测试连接"不必重新输入。"""
    p = body.to_profile()
    if not p.api_key and p.id:
        saved = get_store().get(p.id)
        if saved:
            p.api_key = saved.api_key
    return p


@router.post("/providers/models")
def fetch_models(body: ProfileIn):
    """拉取端点真实可用的模型列表 —— 不在代码里写死会过期的模型名。"""
    try:
        prov = from_profile(_resolve(body))
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        return {"models": prov.list_models()}
    except Exception as exc:
        raise HTTPException(400, f"获取模型列表失败：{exc}") from exc
    finally:
        prov.close()


@router.post("/providers/test")
def test_provider(body: ProfileIn):
    try:
        return probe(_resolve(body))
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
