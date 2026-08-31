"""常见 OpenAI 兼容服务的预设，只是填表的起点，用户可任意修改。

刻意不内置模型名清单 —— 各家模型更新很快，写死必然过期。
连上之后调 GET /models 拉真实列表让用户挑，见 providers.list_models()。
"""
from __future__ import annotations

PRESETS: list[dict] = [
    {
        "key": "dashscope",
        "label": "阿里云百炼（通义千问）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        # 通义系是推理模型，不关思考会让 completion_tokens 涨约 40 倍
        "extra_body": {"enable_thinking": False},
        "note": "qwen3.x 全系默认开启思考，必须保留 enable_thinking=false",
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "extra_body": {},
        "note": "",
    },
    {
        "key": "moonshot",
        "label": "月之暗面 Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "extra_body": {},
        "note": "",
    },
    {
        "key": "zhipu",
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "extra_body": {},
        "note": "",
    },
    {
        "key": "siliconflow",
        "label": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "extra_body": {},
        "note": "聚合多家开源模型",
    },
    {
        "key": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "extra_body": {},
        "note": "",
    },
    {
        "key": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "extra_body": {},
        "note": "聚合网关",
    },
    {
        "key": "ollama",
        "label": "Ollama（本地）",
        "base_url": "http://localhost:11434/v1",
        "extra_body": {},
        "note": "本地模型，api_key 留空即可",
    },
    {
        "key": "llamacpp",
        "label": "llama.cpp（本地）",
        "base_url": "http://localhost:8080/v1",
        "extra_body": {},
        "note": "llama.cpp server 的 /v1 接口，api_key 留空即可",
    },
    {
        "key": "custom",
        "label": "自定义（任意 OpenAI 兼容端点）",
        "base_url": "",
        "extra_body": {},
        "note": "填入以 /v1 结尾的 base_url",
    },
]
