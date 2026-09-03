/**
 * OpenAI 兼容端点调用。浏览器直连，不经过任何自建服务。
 *
 * **CORS 是硬前提**：实测 OpenAI、DeepSeek、OpenRouter、智谱、硅基流动都返回
 * 允许跨域的响应头，可直连；阿里云百炼不返回，浏览器会被拦，需要走转发代理
 * （见 proxy/）。这一点在选服务时就要知道，否则会在"测试连接"时莫名失败。
 */

const RE_FENCE = /^\s*```(?:json)?\s*|\s*```\s*$/g;
const RE_NUMBERED = /^\s*\[(\d+)\]\s*(.*)$/;

/** 剥掉模型回显进译文里的编号标记。
 *  输入段落用 "[N] 原文" 标号，模型有时把标记原样抄进 JSON 的译文值。 */
function stripMarker(text, idx) {
  const m = RE_NUMBERED.exec(text);
  return m && Number(m[1]) === idx ? m[2].trim() : text;
}

/**
 * 容错解析批量翻译结果。
 *
 * 模型并不总是守约，实测同一个 prompt 会得到三种形态：规范 JSON 数组、
 * 裸对象、以及直接模仿输入的 "[0] 译文"。宁可多写几条分支，
 * 也不要把本来可用的译文丢掉。
 */
export function parseSegments(raw, expected) {
  const text = raw.replace(RE_FENCE, "").trim();
  const out = {};
  const take = (items) => {
    for (const it of items) {
      if (!it || typeof it !== "object") continue;
      const idx = Number(it.id);
      const zh = stripMarker(String(it.zh ?? "").trim(), idx);
      if (Number.isFinite(idx) && zh) out[idx] = zh;
    }
  };

  try {
    const data = JSON.parse(text);
    take(Array.isArray(data) ? data : [data]);
    if (Object.keys(out).length) return out;
  } catch { /* 继续尝试其他形态 */ }

  for (const line of text.split("\n")) {
    const t = line.trim().replace(/,$/, "");
    if (t.startsWith("{") && t.endsWith("}")) {
      try { take([JSON.parse(t)]); } catch { /* 跳过 */ }
    }
  }
  if (Object.keys(out).length) return out;

  let cur = null, buf = [];
  for (const line of text.split("\n")) {
    const m = RE_NUMBERED.exec(line);
    if (m) {
      if (cur !== null && buf.length) out[cur] = buf.join("\n").trim();
      cur = Number(m[1]); buf = [m[2]];
    } else if (cur !== null) buf.push(line);
  }
  if (cur !== null && buf.length) out[cur] = buf.join("\n").trim();
  if (Object.keys(out).length) return out;

  if (expected === 1 && text) out[0] = text;
  return out;
}

export class ProviderError extends Error {}

export class Provider {
  /** @param {{baseUrl:string, apiKey:string, model:string, extraBody?:object}} cfg */
  constructor({ baseUrl, apiKey, model, extraBody }) {
    if (!baseUrl) throw new ProviderError("未填写 base_url");
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.apiKey = apiKey || "";
    this.model = model;
    this.extraBody = { ...(extraBody || {}) };
    this._extraOk = true;
  }

  /** 缓存归属标识：决定译文的是「哪个服务的哪个模型」，与档案名无关 */
  get cacheId() {
    return this.baseUrl.replace(/^https?:\/\//, "");
  }

  headers() {
    const h = { "Content-Type": "application/json" };
    if (this.apiKey) h.Authorization = `Bearer ${this.apiKey}`;   // 本地模型可无密钥
    return h;
  }

  async listModels() {
    const r = await fetch(`${this.baseUrl}/models`, { headers: this.headers() });
    if (!r.ok) throw new ProviderError(await describe(r));
    const d = await r.json();
    return (d.data || []).map((m) => String(m.id)).filter(Boolean).sort();
  }

  async chat(system, user, { temperature = 0.3, maxTokens = 4000, model } = {}) {
    const body = {
      model: model || this.model,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature,
      max_tokens: maxTokens,
    };
    if (this._extraOk) Object.assign(body, this.extraBody);

    let r = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST", headers: this.headers(), body: JSON.stringify(body),
    });

    // 端点不认识某个厂商特有参数时会 400（如通义的 enable_thinking 发给 OpenAI）。
    // 去掉附加字段重试一次，这样配置填错也不至于完全用不了。
    if (r.status === 400 && this._extraOk && Object.keys(this.extraBody).length) {
      const msg = (await r.clone().text()).toLowerCase();
      if (Object.keys(this.extraBody).some((k) => msg.includes(k.toLowerCase()))) {
        this._extraOk = false;
        for (const k of Object.keys(this.extraBody)) delete body[k];
        r = await fetch(`${this.baseUrl}/chat/completions`, {
          method: "POST", headers: this.headers(), body: JSON.stringify(body),
        });
      }
    }
    if (!r.ok) throw new ProviderError(await describe(r));

    const d = await r.json();
    if (d.error) throw new ProviderError(d.error.message || JSON.stringify(d.error));
    return {
      text: (d.choices?.[0]?.message?.content || "").trim(),
      usage: {
        prompt: d.usage?.prompt_tokens || 0,
        completion: d.usage?.completion_tokens || 0,
      },
    };
  }
}

async function describe(r) {
  let detail = "";
  try { detail = (await r.text()).slice(0, 300); } catch { /* 忽略 */ }
  if (r.status === 0) return "请求被浏览器拦截，通常是该服务不允许跨域访问";
  return `HTTP ${r.status}${detail ? "：" + detail : ""}`;
}
