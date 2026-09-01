import { useEffect, useState } from "react";
import { api } from "../lib/api";

const blank = {
  id: "", label: "", base_url: "", api_key: "",
  model_translate: "", model_gloss: "", extra_body: {},
};

export default function Settings({ onClose, onChanged }) {
  const [presets, setPresets] = useState([]);
  const [list, setList] = useState([]);
  const [activeId, setActiveId] = useState("");
  const [form, setForm] = useState(blank);
  const [models, setModels] = useState([]);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const [opts, setOpts] = useState({ translate_references: false });
  const [vocab, setVocab] = useState(null);

  const load = async () => {
    const { providers, active } = await api.providers();
    setList(providers);
    setActiveId(active);
    const cur = providers.find((p) => p.id === active) || providers[0];
    if (cur) setForm({ ...cur, api_key: "" });
  };

  useEffect(() => {
    api.presets().then((d) => setPresets(d.presets)).catch(() => {});
    api.options().then(setOpts).catch(() => {});
    api.vocabProfile().then(setVocab).catch(() => {});
    load().catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const applyPreset = (p) =>
    setForm((f) => ({
      ...f,
      label: f.label || p.label,
      base_url: p.base_url,
      extra_body: p.extra_body,
    }));

  const run = async (name, fn) => {
    setBusy(name);
    setResult(null);
    try { return await fn(); }
    catch (e) { setResult({ kind: "err", text: e.message }); }
    finally { setBusy(""); }
  };

  const doModels = () =>
    run("models", async () => {
      const { models } = await api.fetchModels(form);
      setModels(models);
      setResult({ kind: "ok", text: `找到 ${models.length} 个可用模型。` });
    });

  const doTest = () =>
    run("test", async () => {
      const r = await api.testProvider(form);
      if (!r.ok) return setResult({ kind: "err", text: r.error || "未能取得译文" });
      setResult({
        kind: r.warning ? "warn" : "ok",
        text: r.sample,
        usage: r.usage,
        warning: r.warning,
      });
    });

  const doSave = () =>
    run("save", async () => {
      await api.saveProvider(form);
      await load();
      onChanged?.();
      setResult({ kind: "ok", text: "已保存。" });
    });

  const doDelete = (id) =>
    run("del", async () => {
      await api.deleteProvider(id);
      setModels([]);
      setForm(blank);
      await load();
      onChanged?.();
    });

  const doActivate = (id) =>
    run("act", async () => {
      await api.activateProvider(id);
      await load();
      onChanged?.();
    });

  const saveVocab = async (profile) => {
    setVocab((v) => ({ ...v, profile }));
    await api.saveVocabProfile(profile);
    onChanged?.();
  };

  const extraText = JSON.stringify(form.extra_body ?? {}, null, 0);

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label="翻译服务设置">
        <h2>翻译服务</h2>
        <p className="lede">
          填入任意 OpenAI 兼容端点即可 —— 阿里云百炼、DeepSeek、智谱、硅基流动、
          OpenAI，或本机的 Ollama、llama.cpp。密钥只存在你自己的电脑上。
        </p>

        {list.length > 0 && (
          <div className="plist">
            {list.map((p) => (
              <button key={p.id} className="pchip"
                      aria-pressed={p.id === activeId}
                      onClick={() => setForm({ ...p, api_key: "" })}>
                {p.label}
                {p.id === activeId ? " ·使用中" : ""}
              </button>
            ))}
            <button className="pchip" onClick={() => { setForm(blank); setModels([]); }}>
              ＋ 新建
            </button>
          </div>
        )}

        <div className="field">
          <label>服务预设</label>
          <div className="plist" style={{ marginBottom: 0 }}>
            {presets.map((p) => (
              <button key={p.key} className="pchip"
                      aria-pressed={form.base_url === p.base_url && !!p.base_url}
                      onClick={() => applyPreset(p)}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="hint">预设只填好地址，模型仍需在下面选。都可以改。</div>
        </div>

        <div className="row">
          <div className="field">
            <label>名称</label>
            <input value={form.label} onChange={set("label")} placeholder="我的翻译服务" />
          </div>
          <div className="field">
            <label>API 密钥</label>
            <input type="password" value={form.api_key} onChange={set("api_key")}
                   placeholder={form.has_key ? "已保存，留空即不修改" : "sk-…"} />
            <div className="hint">本地模型可留空。</div>
          </div>
        </div>

        <div className="field">
          <label>Base URL</label>
          <input value={form.base_url} onChange={set("base_url")}
                 placeholder="https://api.example.com/v1" />
        </div>

        <div className="row">
          <div className="field">
            <label>翻译模型</label>
            {models.length ? (
              <select value={form.model_translate} onChange={set("model_translate")}>
                <option value="">请选择</option>
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input value={form.model_translate} onChange={set("model_translate")}
                     placeholder="填写或点下方获取列表" />
            )}
          </div>
          <div className="field">
            <label>释义模型</label>
            {models.length ? (
              <select value={form.model_gloss} onChange={set("model_gloss")}>
                <option value="">同翻译模型</option>
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <input value={form.model_gloss} onChange={set("model_gloss")}
                     placeholder="留空则同翻译模型" />
            )}
          </div>
        </div>

        <div className="field">
          <label>附加请求参数</label>
          <textarea
            value={extraText}
            onChange={(e) => {
              try {
                setForm((f) => ({ ...f, extra_body: JSON.parse(e.target.value || "{}") }));
              } catch {
                /* 输入中途不完整属正常，等它成为合法 JSON 再收 */
              }
            }}
          />
          <div className="hint">
            通义千问系列默认开启思考，会让翻译成本涨约 40 倍，需保留{" "}
            <code>{'{"enable_thinking": false}'}</code>。
            其他服务通常留空 <code>{"{}"}</code> 即可；发过去被拒绝时会自动去掉重试。
          </div>
        </div>

        <div className="actions">
          <button className="btn btn-ghost" onClick={doModels} disabled={!!busy || !form.base_url}>
            {busy === "models" ? "获取中…" : "获取模型列表"}
          </button>
          <button className="btn btn-ghost" onClick={doTest} disabled={!!busy || !form.base_url}>
            {busy === "test" ? "测试中…" : "测试连接"}
          </button>
          <span className="spacer" />
          {form.id && form.id !== activeId && (
            <button className="btn btn-ghost" onClick={() => doActivate(form.id)}>设为使用中</button>
          )}
          {form.id && list.length > 1 && (
            <button className="btn btn-ghost" onClick={() => doDelete(form.id)}>删除</button>
          )}
          <button className="btn" onClick={doSave} disabled={!!busy || !form.base_url}>
            {busy === "save" ? "保存中…" : "保存"}
          </button>
          <button className="btn btn-ghost" onClick={onClose}>关闭</button>
        </div>

        <div className="opts">
          <h2 style={{ marginTop: 4 }}>阅读选项</h2>
          <label className="check">
            <input
              type="checkbox"
              checked={opts.translate_references}
              onChange={async (e) => {
                const next = { translate_references: e.target.checked };
                setOpts(next);
                await api.saveOptions(next);
                onChanged?.();
              }}
            />
            <span>
              翻译参考文献
              <em>
                默认不翻译 —— 文献条目译成中文后反而难与原文对照。
                打开后按条整条翻译（同一条的续行会先并回来）。
              </em>
            </span>
          </label>
        </div>

        {vocab && (
          <div className="opts">
            <h2 style={{ marginTop: 4 }}>难词等级</h2>
            {!vocab.available ? (
              <p className="hint">{vocab.hint}</p>
            ) : (
              <>
                <div className="plist">
                  {[["coca", "按词频档位"], ["exam", "按考试大纲"]].map(([k, label]) => (
                    <button key={k} className="pchip"
                            aria-pressed={vocab.profile.basis === k}
                            onClick={() => saveVocab({ ...vocab.profile, basis: k })}>
                      {label}
                    </button>
                  ))}
                </div>
                <div className="plist">
                  {vocab.profile.basis === "coca"
                    ? vocab.coca_tiers.map((t) => (
                        <button key={t} className="pchip"
                                aria-pressed={vocab.profile.coca_tier === t}
                                onClick={() => saveVocab({ ...vocab.profile, coca_tier: t })}>
                          认识前 {t / 1000} 千词
                        </button>
                      ))
                    : vocab.exams.map((e) => (
                        <button key={e.key} className="pchip"
                                aria-pressed={vocab.profile.exam_level === e.key}
                                onClick={() => saveVocab({ ...vocab.profile, exam_level: e.key })}>
                          {e.label}
                        </button>
                      ))}
                </div>
                <div className="hint">
                  超出所选范围的词会在难词模式下标出。范围越大，标注越少。
                </div>
              </>
            )}
          </div>
        )}

        {result && (
          <div className={`result ${result.kind}`}>
            {result.kind === "err" ? <strong>失败　</strong> : <strong>结果　</strong>}
            {result.text}
            {result.usage && (
              <div className="hint" style={{ marginTop: 6 }}>
                本次消耗 {result.usage.prompt_tokens} + {result.usage.completion_tokens} tokens
              </div>
            )}
            {result.warning && (
              <div className="hint" style={{ marginTop: 6 }}>{result.warning}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
