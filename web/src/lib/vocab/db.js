/**
 * 浏览器侧词库：首次访问下载一次，之后存 IndexedDB 复用。
 *
 * 词库是**静态资源**，不含任何用户数据，缓存它不违背「刷新即消失」——
 * 那条约束针对的是你上传的 PDF 与译文，它们只存在于内存里。
 */

const DB_NAME = "pdf-duizhao";
const STORE = "assets";
const KEY = "vocab-v1";

const RE_TOKEN = /[A-Za-z][A-Za-z'\-]*/g;
/** ECDICT 的音标用旧式记号，统一成 IPA 常见写法 */
const PHONETIC_FIX = { "ә": "ə" };

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(key) {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const tx = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
      tx.onsuccess = () => resolve(tx.result);
      tx.onerror = () => resolve(undefined);
    });
  } catch { return undefined; }        // 隐私模式下 IndexedDB 可能不可用
}

async function idbPut(key, value) {
  try {
    const db = await openDb();
    await new Promise((resolve) => {
      const tx = db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
      tx.onsuccess = tx.onerror = () => resolve();
    });
  } catch { /* 存不下就每次重新下载，不影响功能 */ }
}

export class VocabDb {
  constructor(data) {
    this.words = data.words;
    this.lemmaMap = data.lemma;
    this.available = true;
  }

  /** 变形还原为原形。查表优先，查不到再退回规则。 */
  lemma(token) {
    const w = token.toLowerCase().replace(/^['-]+|['-]+$/g, "");
    if (!w) return "";
    const hit = this.lemmaMap[w];
    if (hit) return hit;
    if (this.words[w]) return w;
    return ruleLemma(w);
  }

  get(word) {
    const row = this.words[word.toLowerCase()];
    if (!row) return null;
    const [phonetic, pos, tag, coca, gloss] = row;
    return {
      word: word.toLowerCase(),
      phonetic: [...phonetic].map((c) => PHONETIC_FIX[c] || c).join(""),
      pos, tag, coca, gloss,
      brief: briefOf(gloss),
    };
  }
}

/** 行内显示用的短释义：跟在原词后面，必须短到不撑破行距 */
function briefOf(gloss, maxChars = 8) {
  let first = (gloss || "").split("；")[0].trim();
  first = first.replace(/^(?:n|v|vt|vi|a|ad|adj|adv|prep|conj|pron|int|num|art|aux|abbr)\.\s*/i, "");
  const parts = first.split(/[,，;；、]/).map((s) => s.trim()).filter(Boolean);
  let out = "";
  for (const p of parts.slice(0, 2)) {
    const next = out ? `${out},${p}` : p;
    if (next.length > maxChars && out) break;
    out = next;
  }
  return (out || parts[0] || "").slice(0, maxChars);
}

/** 词表查不到时的兜底规则。只处理最常见的规则变化。 */
function ruleLemma(w) {
  for (const [suf, repl] of [
    ["ies", "y"], ["ied", "y"], ["ying", "ie"],
    ["sses", "ss"], ["shes", "sh"], ["ches", "ch"], ["xes", "x"],
    ["ing", ""], ["ed", ""], ["es", ""], ["s", ""],
  ]) {
    if (w.endsWith(suf) && w.length - suf.length >= 3)
      return w.slice(0, w.length - suf.length) + repl;
  }
  return w;
}

/** 切出英文词，返回 [起点, 终点, 原词]。位置用于在原文上打标记。 */
export function tokenize(text) {
  return [...text.matchAll(RE_TOKEN)].map((m) => [m.index, m.index + m[0].length, m[0]]);
}

let cached = null;

/** 载入词库。首次下载后存 IndexedDB，之后秒开。 */
export async function loadVocab(onProgress) {
  if (cached) return cached;
  const stored = await idbGet(KEY);
  if (stored) {
    cached = new VocabDb(stored);
    return cached;
  }
  onProgress?.("downloading");
  const r = await fetch(`${import.meta.env.BASE_URL}vocab.json`);
  if (!r.ok) throw new Error(`词库下载失败（HTTP ${r.status}）`);
  const data = await r.json();
  await idbPut(KEY, data);
  cached = new VocabDb(data);
  return cached;
}

export function isVocabLoaded() {
  return cached !== null;
}
