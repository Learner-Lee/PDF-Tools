import { useEffect, useState } from "react";
import { PRESETS } from "../lib/presets.js";
import { Provider } from "../lib/translator/provider.js";
import { COCA_TIERS, EXAM_LABELS, EXAM_ORDER } from "../lib/vocab/difficulty.js";

export default function Settings({ config, onSave, onClose }) {
  const [form, setForm] = useState(config);
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => setForm(config), [config]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const patch = (p) => setForm((f) => ({ ...f, ...p }));

  const applyPreset = (p) =>
    patch({ baseUrl: p.baseUrl, extraBody: p.extraBody, presetKey: p.key });

  const preset = PRESETS.find((p) => p.key === form.presetKey);

  const run = async (name, fn) => {
    setBusy(name); setResult(null);
    try { await fn(); }
    catch (e) { setResult({ kind: "err", text: e.message }); }
    finally { setBusy(""); }
  };

  const doModels = () => run("models", async () => {
    const list = await new Provider(form).listModels();
    setModels(list);
    setResult({ kind: "ok", text: `找到 ${list.length} 个可用模型。` });
  });

  const doTest = () => run("test", async () => {
    const p = new Provider(form);
    const { text, usage } = await p.chat(
      "你是翻译助手，只输出译文。",
      "把这句翻译成中文：The mitigation strategy proved efficacious.",
      { maxTokens: 200 }
    );
    setResult({
      kind: usage.completion > 120 ? "warn" : "ok",
      text,
      usage,
      warning: usage.completion > 120
        ? `本次输出 ${usage.completion} tokens，远高于一句翻译所需。该模型可能开启了思考模式，`
          + '建议在附加参数中加入 {"enable_thinking": false} 以大幅降低成本。'
        : "",
    });
  });

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label="设置">
        <h2>翻译服务</h2>
        <p className="lede">
          浏览器直接调用你选定的服务，密钥与译文都不经过本站服务器。
          因此该服务必须允许跨域访问 —— 下面标了「可直连」的都实测可用。
        </p>

        <div className="field">
          <label>服务预设</label>
          <div className="plist" style={{ marginBottom: 0 }}>
            {PRESETS.map((p) => (
              <button key={p.key} className="pchip"
                      aria-pressed={form.presetKey === p.key}
                      onClick={() => applyPreset(p)}>
                {p.label}
                {p.cors === false ? " ·需代理" : p.cors ? " ·可直连" : ""}
              </button>
            ))}
          </div>
          {preset?.note && <div className="hint">{preset.note}</div>}
        </div>

        <div className="row">
          <div className="field">
            <label>API 密钥</label>
            <input type="password" value={form.apiKey} onChange={set("apiKey")}
                   placeholder="sk-…（本机模型可留空）" />
          </div>
          <div className="field">
            <label>模型</label>
            {models.length ? (
              <select value={form.model} onChange={set("model")}>
                <option value="">请选择</option>
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input value={form.model} onChange={set("model")}
                     placeholder="填写或点下方获取列表" />
            )}
          </div>
        </div>

        <div className="field">
          <label>Base URL</label>
          <input value={form.baseUrl} onChange={set("baseUrl")}
                 placeholder="https://api.example.com/v1" />
        </div>

        <div className="field">
          <label>附加请求参数</label>
          <textarea
            value={JSON.stringify(form.extraBody ?? {})}
            onChange={(e) => {
              try { patch({ extraBody: JSON.parse(e.target.value || "{}") }); }
              catch { /* 输入中途不完整属正常 */ }
            }}
          />
          <div className="hint">
            发过去被拒绝时会自动去掉重试，填错不至于完全用不了。
          </div>
        </div>

        <div className="actions">
          <button className="btn btn-ghost" onClick={doModels} disabled={!!busy || !form.baseUrl}>
            {busy === "models" ? "获取中…" : "获取模型列表"}
          </button>
          <button className="btn btn-ghost" onClick={doTest} disabled={!!busy || !form.baseUrl}>
            {busy === "test" ? "测试中…" : "测试连接"}
          </button>
          <span className="spacer" />
          <button className="btn" onClick={() => { onSave(form); onClose(); }}>保存</button>
        </div>

        {result && (
          <div className={`result ${result.kind}`}>
            <strong>{result.kind === "err" ? "失败　" : "结果　"}</strong>
            {result.text}
            {result.usage && (
              <div className="hint" style={{ marginTop: 6 }}>
                本次消耗 {result.usage.prompt} + {result.usage.completion} tokens
              </div>
            )}
            {result.warning && <div className="hint" style={{ marginTop: 6 }}>{result.warning}</div>}
          </div>
        )}

        <div className="opts">
          <h2 style={{ marginTop: 4 }}>阅读选项</h2>
          <label className="check">
            <input type="checkbox" checked={form.translateReferences}
                   onChange={(e) => patch({ translateReferences: e.target.checked })} />
            <span>
              翻译参考文献
              <em>默认不翻译 —— 文献译成中文后反而难与原文对照。打开后按条整条翻译。</em>
            </span>
          </label>
        </div>

        <div className="opts">
          <h2 style={{ marginTop: 4 }}>难词等级</h2>
          <div className="plist">
            {[["coca", "按词频档位"], ["exam", "按考试大纲"]].map(([k, label]) => (
              <button key={k} className="pchip" aria-pressed={form.basis === k}
                      onClick={() => patch({ basis: k })}>{label}</button>
            ))}
          </div>
          <div className="plist">
            {form.basis === "coca"
              ? COCA_TIERS.map((t) => (
                  <button key={t} className="pchip" aria-pressed={form.cocaTier === t}
                          onClick={() => patch({ cocaTier: t })}>
                    认识前 {t / 1000} 千词
                  </button>
                ))
              : EXAM_ORDER.map((k) => (
                  <button key={k} className="pchip" aria-pressed={form.examLevel === k}
                          onClick={() => patch({ examLevel: k })}>
                    {EXAM_LABELS[k]}
                  </button>
                ))}
          </div>
          <div className="hint">超出所选范围的词会在难词模式下标出。范围越大，标注越少。</div>
        </div>

        <p className="note">
          设置存在你自己的浏览器里（localStorage），换台机器要重新填。
          上传的 PDF 与译文只在内存中，刷新即消失。
        </p>
      </div>
    </div>
  );
}
