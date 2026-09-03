import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import pdfjs from "./lib/pdfjs.js";
import { parsePdf } from "./lib/parser/index.js";
import { applyTranslatePolicy, blocks, translatable } from "./lib/parser/model.js";
import { Translator, buildGlossary, extractTerms, formatGlossary, properNouns }
  from "./lib/translator/index.js";
import { Provider } from "./lib/translator/provider.js";
import { analyze } from "./lib/vocab/difficulty.js";
import { loadVocab } from "./lib/vocab/db.js";
import { DEFAULT_CONFIG, isConfigured, loadConfig, saveConfig } from "./lib/config.js";
import { download, toMarkdown } from "./lib/markdown.js";
import PdfPane from "./components/PdfPane.jsx";
import TransPane from "./components/TransPane.jsx";
import HardWordPane from "./components/HardWordPane.jsx";
import Gutter from "./components/Gutter.jsx";
import Settings from "./components/Settings.jsx";

/** 滚到哪译到哪：当前页 + 预取后两页 */
const PREFETCH = 2;

function Dropzone({ onFile, busy, progress, error, configured, onSettings }) {
  const [over, setOver] = useState(false);
  const inputRef = useRef(null);
  return (
    <div className="empty">
      <div className={"drop" + (over ? " is-over" : "")}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}>
        <h1>PDF 对照</h1>
        <p>
          把英文 PDF 拖进来，左边是原页，右边是中文。
          <br />
          <strong>文件不会上传</strong> —— 解析全在你的浏览器里完成，刷新页面即清空。
        </p>
        <input ref={inputRef} type="file" accept="application/pdf" hidden
               onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} />
        <button className="btn" onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? progress : "选择文件"}
        </button>
        {!configured && (
          <p className="note">
            还没配置翻译服务。<button className="linklike" onClick={onSettings}>去设置</button>
          </p>
        )}
        {error && <p className="note note-err">{error}</p>}
      </div>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState(loadConfig);
  const [doc, setDoc] = useState(null);
  const [filename, setFilename] = useState("");
  const [tick, setTick] = useState(0);        // 译文写在块对象上，用它触发重渲染
  const [active, setActive] = useState(null);
  const [folio, setFolio] = useState(1);
  const [mode, setMode] = useState("bilingual");
  const [hardwords, setHardwords] = useState({});
  const [collected, setCollected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [bulk, setBulk] = useState(null);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const enPane = useRef(null);
  const zhPane = useRef(null);
  const syncing = useRef(false);
  const syncTimer = useRef(0);
  const asked = useRef(new Set());
  const askedHw = useRef(new Set());
  const translator = useRef(null);
  const vocab = useRef(null);
  const skipWords = useRef(new Set());

  const configured = isConfigured(config);
  const pages = doc?.pages || [];

  const saveCfg = (next) => {
    setConfig(next);
    saveConfig(next);
    translator.current = null;                 // 换了服务，翻译器要重建
    if (doc) {
      applyTranslatePolicy(doc, next.translateReferences);
      askedHw.current = new Set();
      setHardwords({});
      setTick((t) => t + 1);
    }
  };

  const getTranslator = useCallback(async () => {
    if (!translator.current) {
      translator.current = new Translator(config);
      // 术语表：先扫全文抽高频专有名词，一次调用敲定统一译名
      const texts = translatable(doc).map((b) => b.text);
      const terms = extractTerms(texts);
      const mapping = await buildGlossary(new Provider(config), terms);
      translator.current.glossaryText = formatGlossary(mapping);
      skipWords.current = new Set([
        ...Object.keys(mapping).map((t) => t.toLowerCase()),
        ...properNouns([...blocks(doc)].filter((b) => b.lang !== "zh").map((b) => b.text)),
      ]);
    }
    return translator.current;
  }, [config, doc]);

  // ── 打开文件 ──────────────────────────────────────────
  const onFile = async (file) => {
    setBusy(true); setError(""); setProgress("读取中…");
    try {
      const data = await file.arrayBuffer();
      const parsed = await parsePdf(data, {
        pdfjs,
        onProgress: (d, t) => setProgress(`解析中 ${d}/${t} 页`),
      });
      if (!parsed.isTextPdf) {
        setError("这是扫描版 PDF（没有可提取的文字层），当前只支持文字版。"
          + "图片版需要先做 OCR，功能尚未上线。");
        return;
      }
      applyTranslatePolicy(parsed, config.translateReferences);
      asked.current = new Set();
      askedHw.current = new Set();
      translator.current = null;
      setHardwords({});
      setDoc(parsed);
      setFilename(file.name);
      setFolio(1);
    } catch (e) {
      setError(`解析失败：${e.message}`);
    } finally {
      setBusy(false); setProgress("");
    }
  };

  // ── 懒加载 ────────────────────────────────────────────
  const ensureHardWords = useCallback(async (from) => {
    if (!doc) return;
    const want = [];
    for (let i = from; i < Math.min(from + 1 + PREFETCH, doc.pageCount); i++)
      if (!askedHw.current.has(i)) { askedHw.current.add(i); want.push(i); }
    if (!want.length) return;
    try {
      if (!vocab.current) {
        setProgress("载入词库…");
        vocab.current = await loadVocab();
        setProgress("");
      }
      const add = {};
      for (const b of blocks(doc)) {
        if (!want.includes(b.page) || b.mergedInto || b.lang === "zh") continue;
        if (["header_footer", "watermark", "math", "code", "table", "author"].includes(b.type))
          continue;
        const found = analyze(b.text, config, vocab.current, skipWords.current);
        if (found.length) add[b.id] = found;
      }
      setHardwords((h) => ({ ...h, ...add }));
    } catch (e) {
      want.forEach((i) => askedHw.current.delete(i));
      setError(e.message);
    }
  }, [doc, config]);

  const ensure = useCallback(async (from) => {
    if (!doc) return;
    if (mode === "hardwords") return ensureHardWords(from);
    if (!configured) return;
    const want = [];
    for (let i = from; i < Math.min(from + 1 + PREFETCH, doc.pageCount); i++)
      if (!asked.current.has(i)) { asked.current.add(i); want.push(i); }
    if (!want.length) return;
    try {
      const tr = await getTranslator();
      const todo = [...blocks(doc)].filter(
        (b) => want.includes(b.page) && b.translate && !b.translation && !b.mergedInto
      );
      const tables = [...blocks(doc)].filter(
        (b) => want.includes(b.page) && b.type === "table" && !b.table?.zh
      );
      if (todo.length) await tr.translate(todo);
      if (tables.length) await tr.translateTables(tables);
      setTick((t) => t + 1);
    } catch (e) {
      want.forEach((i) => asked.current.delete(i));
      setError(e.message);
    }
  }, [doc, mode, configured, ensureHardWords, getTranslator]);

  useEffect(() => { if (doc) ensure(0); }, [doc, ensure]);
  useEffect(() => {
    if (doc && mode === "hardwords") ensureHardWords(Math.max(folio - 1, 0));
  }, [mode, doc, folio, ensureHardWords]);

  // ── 滚动同步 ──────────────────────────────────────────
  const nearestTo = (pane, selector) => {
    const line = pane.getBoundingClientRect().top + pane.clientHeight * 0.3;
    let best = null, bestD = Infinity;
    for (const el of pane.querySelectorAll(selector)) {
      const r = el.getBoundingClientRect();
      if (!r.height) continue;
      const d = Math.abs(r.top + r.height / 2 - line);
      if (d < bestD) { bestD = d; best = el.dataset.block; }
    }
    return best;
  };

  /**
   * 同步滚动另一栏。
   * 「程序化滚动中」这个标记必须等目标栏真正停止滚动才解除 —— 用固定超时会在
   * 平滑滚动跨度大时提前解除，尾部事件被当成用户操作，两栏就开始互相弹回。
   */
  const scrollTo = (paneRef, id, smooth = false) => {
    const pane = paneRef.current;
    const el = pane?.querySelector(`[data-block="${CSS.escape(id)}"]`);
    if (!el) return;
    syncing.current = true;
    clearTimeout(syncTimer.current);
    const settle = () => {
      clearTimeout(syncTimer.current);
      syncTimer.current = setTimeout(() => {
        pane.removeEventListener("scroll", settle);
        syncing.current = false;
      }, 140);
    };
    pane.addEventListener("scroll", settle);
    settle();
    // 不能用 offsetTop：左栏的块嵌在 position:relative 的页容器里
    const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top
      + pane.scrollTop - pane.clientHeight * 0.3;
    pane.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
  };

  const onEnScroll = () => {
    const el = enPane.current;
    if (!el) return;
    const mid = el.scrollTop + el.clientHeight * 0.35;
    let cur = 0;
    for (const w of el.querySelectorAll(".page-wrap"))
      if (w.offsetTop <= mid) cur = Number(w.dataset.page);
    setFolio(cur + 1);
    ensure(cur);
    // 滚动只更新高亮，不带动另一栏 —— 两栏各滚各的，
    // 想让对方跟过来时点一下那一段（onPick 的 force 分支）。
    if (syncing.current) return;
    const best = nearestTo(el, ".blockbox:not(.is-skip)");
    if (best && best !== active) setActive(best);
  };

  const onZhScroll = () => {
    const el = zhPane.current;
    if (!el || syncing.current) return;
    const best = nearestTo(el, ".seg-block, .refs-mark");
    if (best && best !== active) setActive(best);
  };

  // 悬停只高亮；点击（force）才把另一栏移到对应位置 —— 这是两栏之间
  // 唯一会产生联动的操作，滚动不会。
  const onPick = (id, side, force = false) => {
    setActive(id);
    if (force) scrollTo(side === "en" ? zhPane : enPane, id, true);
  };

  // ── 全文翻译 / 导出 ───────────────────────────────────
  const translateAll = async () => {
    if (!doc || bulk || !configured) return;
    setError("");
    const todo = [...blocks(doc)].filter((b) => b.translate && !b.translation && !b.mergedInto);
    const tables = [...blocks(doc)].filter((b) => b.type === "table" && !b.table?.zh);
    setBulk({ done: 0, total: todo.length });
    try {
      const tr = await getTranslator();
      await tr.translate(todo, (done, total) => setBulk({ done, total }));
      if (tables.length) await tr.translateTables(tables);
      for (let i = 0; i < doc.pageCount; i++) asked.current.add(i);
      setTick((t) => t + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setBulk(null);
    }
  };

  const exportMd = () => {
    if (!doc) return;
    const base = filename.replace(/\.pdf$/i, "") || "document";
    download(`${base}.zh.md`, toMarkdown(doc, filename));
  };

  const collect = (word, context) => {
    setCollected((s) => {
      const n = new Set(s);
      if (n.has(word.lemma)) n.delete(word.lemma);
      else n.add(word.lemma);
      return n;
    });
    if (!collected.has(word.lemma)) bookRef.current.set(word.lemma, { ...word, context });
    else bookRef.current.delete(word.lemma);
  };
  const bookRef = useRef(new Map());

  const exportBook = (format) => {
    const items = [...bookRef.current.values()];
    if (!items.length) return;
    if (format === "anki") {
      const body = items.map((w) =>
        [w.surface || w.lemma,
         [w.phonetic ? `/${w.phonetic}/` : "", w.gloss,
          w.context ? `<br><i>${w.context}</i>` : ""].filter(Boolean).join(" ")
        ].join("\t").replace(/\n/g, " ")
      ).join("\n");
      download("vocab-anki.txt", body, "text/plain;charset=utf-8");
    } else {
      const esc = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;
      const body = ["单词,原形,音标,词性,释义,语境",
        ...items.map((w) => [w.surface, w.lemma, w.phonetic, w.pos, w.gloss, w.context]
          .map(esc).join(","))].join("\r\n");
      download("vocab.csv", "﻿" + body, "text/csv;charset=utf-8");
    }
  };

  const view = useMemo(() => pages, [pages, tick]);

  if (!doc) {
    return (
      <>
        <div className="bar">
          <span className="wordmark">PDF 对照</span>
          <span className="doc-title" />
          <button className="icon-btn" onClick={() => setShowSettings(true)}>设置</button>
        </div>
        <Dropzone onFile={onFile} busy={busy} progress={progress} error={error}
                  configured={configured} onSettings={() => setShowSettings(true)} />
        {showSettings && (
          <Settings config={config} onSave={saveCfg} onClose={() => setShowSettings(false)} />
        )}
      </>
    );
  }

  const pct = bulk?.total ? bulk.done / bulk.total : 0;

  return (
    <>
      <div className="bar">
        <span className="wordmark">PDF 对照</span>
        <span className="doc-title" title={doc.title || filename}>{doc.title || filename}</span>
        <span className="folio">{folio} / {doc.pageCount}</span>
        <div className="seg">
          <button aria-pressed={mode === "bilingual"} onClick={() => setMode("bilingual")}>对照</button>
          <button aria-pressed={mode === "hardwords"} onClick={() => setMode("hardwords")}>难词</button>
        </div>
        {mode === "hardwords" ? (
          <>
            <button className="icon-btn" onClick={() => exportBook("csv")}
                    disabled={!collected.size}>生词本 CSV {collected.size || ""}</button>
            <button className="icon-btn" onClick={() => exportBook("anki")}
                    disabled={!collected.size}>Anki</button>
          </>
        ) : (
          <button className="icon-btn" onClick={translateAll} disabled={!!bulk || !configured}>
            {bulk ? `翻译全文 ${bulk.done}/${bulk.total}` : "翻译全文"}
          </button>
        )}
        <button className="icon-btn" onClick={exportMd}>导出 Markdown</button>
        <button className="icon-btn" onClick={() => { setDoc(null); setFilename(""); }}>换一份</button>
        <button className="icon-btn" onClick={() => setShowSettings(true)}>设置</button>
        {bulk && <div className="progress"><span style={{ width: `${pct * 100}%` }} /></div>}
      </div>

      {(error || progress) && (
        <div className={`result ${error ? "err" : "ok"}`} style={{ margin: "8px 14px" }}>
          <strong>{error ? "出错　" : "　"}</strong>{error || progress}
        </div>
      )}

      <div className="reader">
        <PdfPane paneRef={enPane} pdf={doc.pdf} pages={view}
                 active={active} onPick={onPick} onScroll={onEnScroll} />
        <Gutter enPane={enPane} zhPane={zhPane} active={active} />
        {mode === "bilingual" ? (
          <TransPane paneRef={zhPane} pages={view} active={active}
                     onPick={onPick} onScroll={onZhScroll} />
        ) : (
          <HardWordPane paneRef={zhPane} pages={view} hardwords={hardwords}
                        active={active} onPick={onPick} onScroll={onZhScroll}
                        collected={collected} onCollect={collect} />
        )}
      </div>

      {showSettings && (
        <Settings config={config} onSave={saveCfg} onClose={() => setShowSettings(false)} />
      )}
    </>
  );
}
