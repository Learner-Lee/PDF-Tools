"""具体 Provider：Qwen（默认）与本地 llama.cpp。"""
from __future__ import annotations

from ..config import settings
from .base import OpenAICompatProvider, ProviderError


class QwenProvider(OpenAICompatProvider):
    name = "qwen"

    def __init__(self, model: str | None = None):
        if not settings.qwen_api_key:
            raise ProviderError("QWEN_API_KEY 未配置，请在 .env 中填写")
        super().__init__(
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
            model=model or settings.qwen_model_translate,
        )


class LlamaCppProvider(OpenAICompatProvider):
    """llama.cpp server 的 /v1 接口，与 Qwen 共用调用实现。"""

    name = "llamacpp"

    def __init__(self, model: str | None = None):
        super().__init__(
            base_url=settings.llamacpp_base_url,
            api_key="",
            model=model or settings.llamacpp_model,
        )


def get_provider(kind: str | None = None, model: str | None = None) -> OpenAICompatProvider:
    kind = kind or settings.provider
    if kind == "qwen":
        return QwenProvider(model)
    if kind == "llamacpp":
        return LlamaCppProvider(model)
    raise ProviderError(f"未知 provider: {kind}")
