"""按用户配置的档案构造 Provider。

不绑定任何厂商：所有 OpenAI 兼容端点走同一份实现，
差异全部收敛到 ProviderProfile（base_url / api_key / model / extra_body）。
"""
from __future__ import annotations

from ..store import ProviderProfile, get_store
from .base import OpenAICompatProvider, ProviderError


def from_profile(p: ProviderProfile, *, model: str | None = None) -> OpenAICompatProvider:
    if not p.base_url:
        raise ProviderError(f"档案「{p.label}」未填写 base_url")
    return OpenAICompatProvider(
        base_url=p.base_url,
        api_key=p.api_key,
        model=model or p.model_translate,
        name=p.id,
        extra_body=p.extra_body,
    )


def get_provider(
    profile_id: str | None = None, model: str | None = None
) -> OpenAICompatProvider:
    """取当前启用的档案；传 profile_id 可指定用哪一个。"""
    store = get_store()
    p = store.get(profile_id) if profile_id else store.active()
    if p is None:
        raise ProviderError(
            "尚未配置任何翻译服务。请在设置中添加一个 OpenAI 兼容端点"
            "（填入 base_url、api_key 与模型名）。"
        )
    return from_profile(p, model=model)


def get_gloss_provider(profile_id: str | None = None) -> OpenAICompatProvider:
    """术语表/难词释义用的 Provider，可与翻译用不同模型。"""
    store = get_store()
    p = store.get(profile_id) if profile_id else store.active()
    if p is None:
        raise ProviderError("尚未配置任何翻译服务。")
    return from_profile(p, model=p.model_gloss or p.model_translate)


def probe(p: ProviderProfile) -> dict:
    """连通性自检：拉模型列表 + 试译一句，用于设置界面的"测试连接"。"""
    prov = from_profile(p)
    out: dict = {"ok": False, "models": [], "sample": "", "error": ""}
    try:
        out["models"] = prov.list_models()
    except Exception as exc:
        out["error"] = f"模型列表获取失败（不影响使用）：{exc}"
    try:
        text, usage = prov.chat(
            "你是翻译助手，只输出译文。",
            "把这句翻译成中文：The mitigation strategy proved efficacious.",
            max_tokens=200,
        )
        out["sample"] = text
        out["ok"] = bool(text)
        out["usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }
        # 思考模式没关掉时 completion_tokens 会异常高，直接提示用户
        if usage.completion_tokens > 120:
            out["warning"] = (
                f"本次输出 {usage.completion_tokens} tokens，远高于一句翻译所需。"
                "该模型可能开启了思考模式，建议在附加参数中加入 "
                '{"enable_thinking": false} 以大幅降低成本。'
            )
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        prov.close()
    return out
