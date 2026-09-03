import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./lib/api";
import PdfPane from "./components/PdfPane";
import TransPane from "./components/TransPane";
import HardWordPane from "./components/HardWordPane";
import VocabBook from "./components/VocabBook";
import Gutter from "./components/Gutter";
import Settings from "./components/Settings";

/** 滚到哪译到哪：当前页 + 预取后两页 */
const PREFETCH = 2;

/** 把译文与表格结果回填进页面数据 */
function applyTranslations(pages, translations = {}, tables = {}) {
  return pages.map((p) => ({
    ...p,
    blocks: p.blocks.map((b) => {
      if (tables[b.id]) return { ...b, table: tables[b.id] };
      if (translations[b.id]) return { ...b, translation: translations[b.id] };
      return b;
    }),
  }));
}

function Dropzone({ onFile, onOpen, recent, error, busy, progress }) {
  const [over, setOver] = useState(false);
  const inputRef = useRef(null);
  return (
    <div className="empty">
      <div
        className={"drop" + (over ? " is-over" : "")}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
      >
        <h1>PDF 对照</h1>
        <p>
          把英文 PDF 拖进来，左边是原页，右边是中文。
          <br />
          当前支持文字版 PDF；扫描件需要 OCR，还没做。
        </p>
        <input ref={inputRef} type="file" accept="application/pdf" hidden
               onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} />
        <button className="btn" onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? `读取中 ${Math.round(progress * 100)}%` : "选择文件"}
        </button>
        {error && <p className="note note-err">{error}</p>}

        {recent.length > 0 && (
          <div className="recent">
            <div className="recent-label">最近打开</div>
            {recent.map((r) => (
              <button key={r.file_hash} className="recent-item"
                      onClick={() => onOpen(r.file_hash)} disabled={busy}>
                <span className="recent-name">{r.filename}</span>
                <span className="folio">{r.page_count} 页</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [doc, setDoc] = useState(null);
  const [pages, setPages] = useState([]);
  const [active, setActive] = useState(null);
  const [folio, setFolio] = useState(1);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [bulk, setBulk] = useState(null);
  const [recent, setRecent] = useState([]);
  const [mode, setMode] = useState("bilingual");   // bilingual | hardwords
  const [hardwords, setHardwords] = useState({});
  const [collected, setCollected] = useState(new Set());
  const [showBook, setShowBook] = useState(false);
  const [exporting, setExporting] = useState("");

  const enPane = useRef(null);
  const zhPane = useRef(null);
  const syncing = useRef(false);
  const syncTimer = useRef(0);
  const asked = useRef(new Set());
  const askedHw = useRef(new Set());

  useEffect(() => {
    if (!doc) api.list().then((d) => setRecent(d.documents)).catch(() => {});
  }, [doc]);

  const open = async (summary) => {
    const { pages } = await api.pages(summary.id);
    asked.current = new Set();
    setDoc(summary);
    setPages(pages);
    setFolio(1);
  };

  // ── 打开已解析过的文档 ────────────────────────────────
  const onOpen = async (id) => {
    setBusy(true); setError("");
    try { await open(await api.doc(id)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  // ── 上传 ──────────────────────────────────────────────
  const onFile = async (file) => {
    setBusy(true); setError(""); setProgress(0);
    try {
      await open(await api.upload(file, setProgress));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // ── 懒加载翻译 ────────────────────────────────────────
  const ensureHardWords = useCallback(
    async (from) => {
      if (!doc) return;
      const want = [];
      for (let i = from; i < Math.min(from + 1 + PREFETCH, doc.page_count); i++) {
        if (!askedHw.current.has(i)) { askedHw.current.add(i); want.push(i); }
      }
      if (!want.length) return;
      try {
        const { hardwords } = await api.hardWords(doc.id, want);
        setHardwords((h) => ({ ...h, ...hardwords }));
      } catch (e) {
        want.forEach((i) => askedHw.current.delete(i));
        setError(e.message);
      }
    },
    [doc]
  );

  const ensure = useCallback(
    async (from) => {
      if (!doc) return;
      if (mode === "hardwords") return ensureHardWords(from);
      const want = [];
      for (let i = from; i < Math.min(from + 1 + PREFETCH, doc.page_count); i++) {
        if (!asked.current.has(i)) { asked.current.add(i); want.push(i); }
      }
      if (!want.length) return;
      try {
        const { translations, tables } = await api.translate(doc.id, want);
        if (!Object.keys(translations).length && !Object.keys(tables || {}).length) return;
        setPages((ps) => applyTranslations(ps, translations, tables));
      } catch (e) {
        want.forEach((i) => asked.current.delete(i));   // 失败可重试
        setError(e.message);
      }
    },
    [doc, mode, ensureHardWords]
  );

  useEffect(() => { if (doc) ensure(0); }, [doc, ensure]);

  useEffect(() => {
    api.book().then((d) => setCollected(new Set(d.items.map((i) => i.lemma))))
      .catch(() => {});
  }, []);

  // 切换到难词模式时按当前页取一次，不必等下一次滚动
  useEffect(() => {
    if (doc && mode === "hardwords") ensureHardWords(Math.max(folio - 1, 0));
  }, [mode, doc, folio, ensureHardWords]);

  const collect = async (word, context) => {
    if (collected.has(word.lemma)) {
      await api.removeWord(word.lemma);
      setCollected((s) => { const n = new Set(s); n.delete(word.lemma); return n; });
      return;
    }
    await api.addWord({
      lemma: word.lemma, surface: word.surface, phonetic: word.phonetic,
      pos: word.pos, gloss: word.gloss, context, doc_id: doc.id,
    });
    setCollected((s) => new Set(s).add(word.lemma));
  };

  // ── 滚动：定位当前页、驱动懒加载、决定活动段 ───────────
  const onEnScroll = () => {
    const el = enPane.current;
    if (!el) return;
    const mid = el.scrollTop + el.clientHeight * 0.35;
    let cur = 0;
    for (const w of el.querySelectorAll(".page-wrap")) {
      if (w.offsetTop <= mid) cur = Number(w.dataset.page);
    }
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

  /** 取该栏视线高度（顶部 30% 处）最近的块 id */
  const nearestTo = (pane, selector) => {
    const line = pane.getBoundingClientRect().top + pane.clientHeight * 0.3;
    let best = null, bestD = Infinity;
    for (const el of pane.querySelectorAll(selector)) {
      const r = el.getBoundingClientRect();
      if (r.height === 0) continue;
      const d = Math.abs(r.top + r.height / 2 - line);
      if (d < bestD) { bestD = d; best = el.dataset.block; }
    }
    return best;
  };

  /**
   * 同步滚动另一栏。
   *
   * 关键是"程序化滚动中"这个标记何时解除：用固定超时会在平滑滚动跨度大时
   * 提前解除，尾部的滚动事件被当成用户操作，触发反向同步，两栏就开始互相弹回。
   * 改为等目标栏真正停止滚动（最后一个 scroll 事件后 140ms）再解除。
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

    // 不能用 offsetTop：左栏的块嵌在 position:relative 的 .page-wrap 里，
    // offsetParent 是页面而非栏，拿到的是页内偏移。按 rect 差值算才对两栏都成立。
    const top =
      el.getBoundingClientRect().top -
      pane.getBoundingClientRect().top +
      pane.scrollTop -
      pane.clientHeight * 0.3;
    pane.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
  };

  // 悬停只高亮；点击（force）才把另一栏移到对应位置 —— 这是两栏之间
  // 唯一会产生联动的操作，滚动不会。
  const onPick = (id, side, force = false) => {
    setActive(id);
    if (force) scrollTo(side === "en" ? zhPane : enPane, id, true);
  };

  // 设置改动后重新取一遍页面数据：哪些块该翻译由后端按当前策略重算
  const reload = useCallback(async () => {
    if (!doc) return;
    try {
      const { pages } = await api.pages(doc.id);
      asked.current = new Set();
      askedHw.current = new Set();
      setHardwords({});
      setPages(pages);
      ensure(0);
    } catch (e) {
      setError(e.message);
    }
  }, [doc, ensure]);

  // 换了模型或译文不理想时的退路。命中缓存的部分不会重新花钱。
  const retranslate = async () => {
    if (!doc || bulk) return;
    setError("");
    try {
      await api.retranslate(doc.id);
      const { pages } = await api.pages(doc.id);
      asked.current = new Set();
      setPages(pages);
      ensure(0);
    } catch (e) {
      setError(e.message);
    }
  };

  const exportDoc = async (format) => {
    if (!doc || exporting) return;
    setError("");
    setExporting(format);
    try {
      const base = (doc.filename || doc.title || "document").replace(/\.pdf$/i, "");
      const msg = await api.exportDoc(doc.id, format, `${base}.zh.${format}`);
      if (msg) setError(msg);
    } catch (e) {
      setError(e.message);
    } finally {
      setExporting("");
    }
  };

  // ── 全文翻译 ──────────────────────────────────────────
  const translateAll = async () => {
    if (!doc || bulk) return;
    setError("");
    setBulk({ done: 0, total: 0 });
    try {
      await api.translateAll(doc.id, (ev) => {
        if (ev.type === "start") setBulk({ done: 0, total: ev.total });
        else if (ev.type === "progress") setBulk({ done: ev.done, total: ev.total });
        else if (ev.type === "error") setError(ev.message);
        else if (ev.type === "done") {
          setPages((ps) => applyTranslations(ps, ev.translations, ev.tables));
          for (let i = 0; i < doc.page_count; i++) asked.current.add(i);
        }
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBulk(null);
    }
  };

  if (!doc) {
    return (
      <>
        <div className="bar">
          <span className="wordmark">PDF 对照</span>
          <span className="doc-title" />
          <button className="icon-btn" onClick={() => setShowSettings(true)}>设置</button>
        </div>
        <Dropzone onFile={onFile} onOpen={onOpen} recent={recent}
                  error={error} busy={busy} progress={progress} />
        {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      </>
    );
  }

  const pct = bulk?.total ? bulk.done / bulk.total : 0;

  return (
    <>
      <div className="bar">
        <span className="wordmark">PDF 对照</span>
        <span className="doc-title" title={doc.title}>{doc.title}</span>
        <span className="folio">{folio} / {doc.page_count}</span>
        <div className="seg">
          <button aria-pressed={mode === "bilingual"} onClick={() => setMode("bilingual")}>
            对照
          </button>
          <button aria-pressed={mode === "hardwords"} onClick={() => setMode("hardwords")}>
            难词
          </button>
        </div>
        {mode === "hardwords" ? (
          <button className="icon-btn" onClick={() => setShowBook(true)}>
            生词本 {collected.size || ""}
          </button>
        ) : (
          <button className="icon-btn" onClick={translateAll} disabled={!!bulk}>
            {bulk ? `翻译全文 ${bulk.done}/${bulk.total}` : "翻译全文"}
          </button>
        )}
        <button className="icon-btn" onClick={() => exportDoc("pdf")}
                disabled={!!bulk || !!exporting}
                title="保留原版式的中文 PDF">
          {exporting === "pdf" ? "导出中…" : "导出 PDF"}
        </button>
        <button className="icon-btn" onClick={() => exportDoc("md")}
                disabled={!!bulk || !!exporting}
                title="丢版式但内容完整，可二次编辑">
          {exporting === "md" ? "导出中…" : "Markdown"}
        </button>
        <button className="icon-btn" onClick={retranslate} disabled={!!bulk}>
          重新翻译
        </button>
        <button className="icon-btn" onClick={() => { setDoc(null); setPages([]); }}>
          换一份
        </button>
        <button className="icon-btn" onClick={() => setShowSettings(true)}>设置</button>
        {bulk && <div className="progress"><span style={{ width: `${pct * 100}%` }} /></div>}
      </div>

      {error && (
        <div className="result err" style={{ margin: "8px 14px" }}>
          <strong>出错　</strong>{error}
        </div>
      )}

      <div className="reader">
        <PdfPane paneRef={enPane} docId={doc.id} pages={pages}
                 active={active} onPick={onPick} onScroll={onEnScroll} />
        <Gutter enPane={enPane} zhPane={zhPane} active={active} />
        {mode === "bilingual" ? (
          <TransPane paneRef={zhPane} pages={pages} active={active}
                     onPick={onPick} onScroll={onZhScroll} />
        ) : (
          <HardWordPane paneRef={zhPane} pages={pages} hardwords={hardwords}
                        active={active} onPick={onPick} onScroll={onZhScroll}
                        collected={collected} onCollect={collect} />
        )}
      </div>

      {showSettings && (
        <Settings onClose={() => setShowSettings(false)} onChanged={reload} />
      )}
      {showBook && (
        <VocabBook
          onClose={() => setShowBook(false)}
          onChanged={() => api.book().then((d) =>
            setCollected(new Set(d.items.map((i) => i.lemma))))}
        />
      )}
    </>
  );
}
