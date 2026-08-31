"""翻译 Provider 抽象。

Qwen 与 llama.cpp 都走 OpenAI 兼容协议，因此共用一份调用实现，
切换只需换 base_url 与 model —— 这是当初选型时就定下的约束。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

_RE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


class ProviderError(RuntimeError):
    pass


class OpenAICompatProvider:
    """OpenAI 兼容接口的通用实现。"""

    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 180.0):
        if not base_url:
            raise ProviderError(f"{self.name}: base_url 未配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=timeout)

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4000,
        model: str | None = None,
    ) -> tuple[str, Usage]:
        payload = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 硬性默认值，不做成可选项：qwen3.x 全系是推理模型，开启思考会让
            # 一句翻译的 completion_tokens 从 7 涨到 300+，批量翻译成本差约 40 倍。
            "enable_thinking": False,
        }
        r = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if r.status_code != 200:
            raise ProviderError(f"{self.name} HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        if "error" in data:
            raise ProviderError(f"{self.name}: {data['error']}")
        msg = data["choices"][0]["message"]
        u = data.get("usage") or {}
        return (msg.get("content") or "").strip(), Usage(
            u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        )

    def close(self) -> None:
        self._client.close()


_RE_NUMBERED = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


def parse_json_array(raw: str) -> list[dict]:
    """剥离可能的代码围栏后解析 JSON 数组（严格路径）。"""
    text = _RE_FENCE.sub("", raw.strip())
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("期望 JSON 数组")
    return data


def parse_segments(raw: str, expected: int) -> dict[int, str]:
    """容错解析批量翻译结果，返回 {编号: 译文}。

    模型并不总是守约。实测同一个 prompt 会得到三种形态：
      1. 规范的 JSON 数组
      2. 裸对象 {"id":0,"zh":"..."}（单段时尤其常见）
      3. 直接模仿输入的编号格式 "[0] 译文"
    宁可多写几条解析分支，也不要把本来可用的译文丢掉。
    """
    text = _RE_FENCE.sub("", raw.strip())
    out: dict[int, str] = {}

    def take(items) -> None:
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                idx, zh = int(it["id"]), str(it["zh"]).strip()
            except (KeyError, ValueError, TypeError):
                continue
            if zh:
                out[idx] = zh

    # 1) 整体就是合法 JSON：数组或裸对象
    try:
        data = json.loads(text)
        take(data if isinstance(data, list) else [data])
        if out:
            return out
    except json.JSONDecodeError:
        pass

    # 2) 逐行 JSON 对象（JSONL，或数组被拆行输出）
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("{") and line.endswith("}"):
            try:
                take([json.loads(line)])
            except json.JSONDecodeError:
                continue
    if out:
        return out

    # 3) "[N] 译文" 编号格式：模型常直接沿用输入的样子
    cur: int | None = None
    buf: list[str] = []
    for line in text.splitlines():
        m = _RE_NUMBERED.match(line)
        if m:
            if cur is not None and buf:
                out[cur] = "\n".join(buf).strip()
            cur, buf = int(m.group(1)), [m.group(2)]
        elif cur is not None:
            buf.append(line)
    if cur is not None and buf:
        out[cur] = "\n".join(buf).strip()
    if out:
        return out

    # 4) 只有一段时，整段回复就是译文
    if expected == 1 and text:
        out[0] = text
    return out
