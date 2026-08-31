"""翻译 Provider 抽象。

Qwen 与 llama.cpp 都走 OpenAI 兼容协议，因此共用一份调用实现，
切换只需换 base_url 与 model —— 这是当初选型时就定下的约束。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

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

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        name: str = "openai-compat",
        extra_body: dict | None = None,
        timeout: float = 180.0,
    ):
        if not base_url:
            raise ProviderError("base_url 未配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        # 厂商特有的请求体字段（如通义的 enable_thinking）。不写死在代码里，
        # 因为把它发给 OpenAI 之类不认识该参数的服务会直接 400。
        self.extra_body = dict(extra_body or {})
        self._extra_ok = True
        self._client = httpx.Client(timeout=timeout)

    @property
    def cache_id(self) -> str:
        """缓存归属标识。

        用端点地址而非档案 id：决定译文的是"哪个服务的哪个模型"，
        与用户给档案起的名字无关。档案改名、删了重建都不该让缓存失效。
        """
        return self.base_url.split("://", 1)[-1]

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:                       # 本地模型通常不需要密钥
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def list_models(self) -> list[str]:
        """拉取该端点真实可用的模型列表，避免在代码里写死会过期的模型名。"""
        r = self._client.get(f"{self.base_url}/models", headers=self._headers())
        if r.status_code != 200:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json().get("data") or []
        return sorted(str(m.get("id")) for m in data if m.get("id"))

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
        }
        if self._extra_ok:
            payload.update(self.extra_body)

        r = self._client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
        )
        # 端点不认识某个厂商特有参数时会 400。去掉附加字段重试一次，
        # 这样一份配置填错了 extra_body 也不至于完全用不了。
        if r.status_code == 400 and self._extra_ok and self.extra_body:
            body = r.text.lower()
            if any(k.lower() in body for k in self.extra_body):
                log.warning("%s 不支持附加参数 %s，已停用", self.name, list(self.extra_body))
                self._extra_ok = False
                payload = {k: v for k, v in payload.items() if k not in self.extra_body}
                r = self._client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
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


def _strip_marker(text: str, idx: int) -> str:
    """剥掉模型回显进译文里的编号标记。

    输入段落用 "[N] 原文" 标号，模型有时把这个标记原样抄进 JSON 的译文值里，
    得到 "[1] GPT-5" 这种结果。只在编号与该段一致时剥离，
    以免误伤正文里本来就有的引用标记。
    """
    m = _RE_NUMBERED.match(text)
    if m and int(m.group(1)) == idx:
        return m.group(2).strip()
    return text


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
            zh = _strip_marker(zh, idx)
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
