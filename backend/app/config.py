"""启动种子配置。

.env 只在首次运行、库中还没有任何 provider 档案时用来建一份初始配置。
之后一切以 SQLite 中的档案为准（见 store.py），用户可在设置界面随时改，
因此任何厂商信息都不应写死在代码路径上。密钥永不入库（git）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

STORAGE = ROOT / "storage"
STORAGE.mkdir(exist_ok=True)
CACHE_DB = STORAGE / "cache.db"


@dataclass(frozen=True)
class Settings:
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_base_url: str = os.getenv("QWEN_BASE_URL", "")
    qwen_model_translate: str = os.getenv("QWEN_MODEL_TRANSLATE", "qwen3.6-flash")
    qwen_model_gloss: str = os.getenv("QWEN_MODEL_GLOSS", "qwen3.6-flash")

    llamacpp_base_url: str = os.getenv("LLAMACPP_BASE_URL", "http://localhost:8080/v1")
    llamacpp_model: str = os.getenv("LLAMACPP_MODEL", "local")

    target_lang: str = "zh"


settings = Settings()
