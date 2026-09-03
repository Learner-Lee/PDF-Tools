/**
 * 翻译编排：批处理、术语表、失败降级。
 *
 * 缓存只在内存里（Map）—— 刷新页面即清空，与「不留任何痕迹」的定位一致。
 * 同一次会话内，对照阅读与全文翻译共用它，看过的页不会重复付费。
 */
import { Provider, ProviderError, parseSegments } from "./provider.js";

/** 单批上限。批越大越省 prompt 开销，一旦解析失败重试代价也越大。 */
const MAX_BATCH_CHARS = 2000;
const MAX_BATCH_SEGMENTS = 10;

const SYSTEM = `你是专业的学术论文翻译，把英文准确译成简体中文。

要求：
1. 忠实、通顺、术语准确，保持学术语体，不添加原文没有的内容。
2. 保留原文中的数字、公式、变量名、引用标记（如 (Wang et al., 2023)、Table 2、Figure 1）。
3. 保留原文中已有的中文内容，原样输出，不要改写。
4. 人名、机构名、模型名、产品名保留原文。
5. 只翻译，不解释、不评论、不补充。

严格输出 JSON 数组，每个元素形如 {"id":<编号>,"zh":"<译文>"}，
数组长度必须与输入段落数一致，不要输出任何其他内容。`;

/** 单段降级用。实测单段时模型极易改用 "[0] 译文" 或裸对象，
 *  与其和它较劲格式，不如直接收纯文本，反而更稳。 */
const SYSTEM_SINGLE = `你是专业的学术论文翻译，把英文准确译成简体中文。

要求：忠实通顺、术语准确；保留数字、公式、引用标记；保留原文中已有的中文；
人名机构名模型名保留原文。只输出译文本身，不要编号、不要 JSON、不要任何解释。`;

const RE_HAS_LETTER = /[A-Za-z一-鿿]/;

/** 不含字母的格子（纯数字、百分比、破折号）无需翻译，送去只会被改坏 */
export function needsTranslation(text) {
  return RE_HAS_LETTER.test(text || "");
}

function batch(items) {
  const out = [];
  let cur = [], size = 0;
  for (const b of items) {
    const n = b.text.length;
    if (cur.length && (size + n > MAX_BATCH_CHARS || cur.length >= MAX_BATCH_SEGMENTS)) {
      out.push(cur); cur = []; size = 0;
    }
    cur.push(b); size += n;
  }
  if (cur.length) out.push(cur);
  return out;
}

export class Translator {
  constructor(config) {
    this.provider = new Provider(config);
    this.cache = new Map();          // 刷新即清空，不落任何持久存储
    this.glossaryText = "";
    this.usage = { prompt: 0, completion: 0, calls: 0 };
  }

  key(text) {
    return `${this.provider.cacheId}|${this.provider.model}|${text}`;
  }

  system(single = false) {
    const base = single ? SYSTEM_SINGLE : SYSTEM;
    return this.glossaryText ? base + "\n\n" + this.glossaryText : base;
  }

  async callBatch(items) {
    const user = items.map((b, i) => `[${i}] ${b.text}`).join("\n\n");
    const { text, usage } = await this.provider.chat(this.system(), user);
    this.usage.prompt += usage.prompt;
    this.usage.completion += usage.completion;
    this.usage.calls += 1;
    return parseSegments(text, items.length);
  }

  async callOne(item) {
    try {
      const { text, usage } = await this.provider.chat(this.system(true), item.text);
      this.usage.prompt += usage.prompt;
      this.usage.completion += usage.completion;
      this.usage.calls += 1;
      return text.replace(/^`+|`+$/g, "").trim() || null;
    } catch {
      return null;
    }
  }

  /**
   * 翻译一批块。命中缓存的不重复调用。
   * @param {(done:number,total:number)=>void} [onProgress]
   */
  async translate(items, onProgress) {
    const result = { translated: 0, fromCache: 0, failed: [] };
    const pending = [];
    for (const b of items) {
      const hit = this.cache.get(this.key(b.text));
      if (hit !== undefined) { b.translation = hit; result.fromCache++; }
      else pending.push(b);
    }

    let done = result.fromCache;
    for (const group of batch(pending)) {
      let got = {};
      try {
        got = await this.callBatch(group);
      } catch (e) {
        if (e instanceof ProviderError && /跨域|CORS/i.test(e.message)) throw e;
        got = {};
      }
      // 返回条数对不上就逐条补，绝不让译文与段落错位
      const missing = group.map((_, i) => i).filter((i) => !got[i]);
      for (const i of missing) {
        const t = await this.callOne(group[i]);
        if (t) got[i] = t;
      }
      group.forEach((b, i) => {
        if (got[i]) {
          b.translation = got[i];
          this.cache.set(this.key(b.text), got[i]);
          result.translated++;
        } else result.failed.push(b.id);
        done++;
      });
      onProgress?.(done, items.length);
    }
    return result;
  }

  /** 表格逐格翻译：表格是结构，行列必须原样保住 */
  async translateTables(tableBlocks, onProgress) {
    const seen = new Set();
    const cells = [];
    for (const blk of tableBlocks) {
      for (const row of blk.table?.rows || []) {
        for (const cell of row) {
          const t = (cell || "").trim();
          if (t && !seen.has(t) && needsTranslation(t)) {
            seen.add(t);
            cells.push({ id: `cell${cells.length}`, text: t, translation: null });
          }
        }
      }
    }
    if (!cells.length) return { translated: 0, fromCache: 0, failed: [] };

    const r = await this.translate(cells, onProgress);
    const map = new Map(cells.filter((c) => c.translation).map((c) => [c.text, c.translation]));
    for (const blk of tableBlocks) {
      if (!blk.table) continue;
      blk.table.zh = blk.table.rows.map((row) =>
        row.map((c) => map.get((c || "").trim()) ?? c)
      );
    }
    return r;
  }
}

export { Provider, ProviderError, parseSegments } from "./provider.js";
export { extractTerms, buildGlossary, formatGlossary, properNouns } from "./glossary.js";
