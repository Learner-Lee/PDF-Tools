/**
 * 术语表：保证全篇译名一致。
 *
 * 长文档分批翻译时，同一个专有名词很容易在不同批次被译成不同说法。
 * 先扫全文抽高频专有名词，用一次调用敲定统一译名，再注入每批的 system prompt。
 */

const RE_ACRONYM = /\b[A-Z][A-Z0-9]{1,}(?:[-‑][A-Za-z0-9]+)*\b/g;
const RE_PROPER = /\b[A-Z][a-z]{2,}(?:[-‑][A-Z]?[a-z]+)*\b/g;
const RE_LOWER = /\b[a-z]{3,}\b/g;

const STOP = new Set([
  "The","This","That","These","Those","There","Then","They","Their","We","Our","It","Its",
  "In","For","From","With","When","While","However","Table","Figure","Section","Appendix",
  "First","Second","Third","Finally","Both","Each","All","Some","Such","Because","Although",
  "After","Before","Since","Given","Using","Overall","Beyond","Under","Across","Based",
  "Results","Model","Models",
]);

/**
 * 抽取需要统一译名的专有名词与缩写。
 *
 * 关键去噪判据：若某个大写词的小写形式也在文中出现过（social / Social），
 * 说明它只是句首大写的普通词。不做这步，术语表会被 Social、Human、Full
 * 这类词淹没并污染每一批的 prompt。
 */
export function extractTerms(texts, { minFreq = 3, limit = 60 } = {}) {
  const lowerSeen = new Set();
  for (const t of texts) for (const m of t.matchAll(RE_LOWER)) lowerSeen.add(m[0]);

  const counter = new Map();
  const bump = (w, n) => counter.set(w, (counter.get(w) || 0) + n);
  for (const t of texts) {
    for (const m of t.matchAll(RE_ACRONYM)) bump(m[0], 2);   // 缩写最需要统一
    for (const m of t.matchAll(RE_PROPER)) {
      if (!STOP.has(m[0]) && !lowerSeen.has(m[0].toLowerCase())) bump(m[0], 1);
    }
  }
  return [...counter.entries()]
    .filter(([, c]) => c >= minFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([w]) => w);
}

/** 全文中的专有名词（小写形式），供难词标注排除 —— 作者名、机构名不该当难词 */
export function properNouns(texts) {
  const lowerSeen = new Set();
  for (const t of texts) for (const m of t.matchAll(RE_LOWER)) lowerSeen.add(m[0]);
  const out = new Set();
  for (const t of texts) {
    for (const m of t.matchAll(RE_PROPER))
      if (!STOP.has(m[0]) && !lowerSeen.has(m[0].toLowerCase())) out.add(m[0].toLowerCase());
    for (const m of t.matchAll(RE_ACRONYM)) out.add(m[0].toLowerCase());
  }
  return out;
}

const GLOSSARY_SYSTEM =
  "你是学术翻译的术语专家。用户会给出一篇英文论文中的高频术语与专有名词。" +
  "请为每个词给出该领域最通行的中文译名。" +
  "若该词是应当保留原文的缩写、模型名、产品名或代号（如 GPT-5、LLM），rendering 直接填原词。" +
  '严格输出 JSON 数组，元素形如 {"term":"<原词>","rendering":"<中文或原词>"}，不要输出其他内容。';

export async function buildGlossary(provider, terms) {
  if (!terms.length) return {};
  let items;
  try {
    const { text } = await provider.chat(GLOSSARY_SYSTEM, terms.join("\n"),
      { temperature: 0, maxTokens: 2000 });
    items = JSON.parse(text.replace(/^\s*```(?:json)?\s*|\s*```\s*$/g, "").trim());
  } catch {
    return {};                       // 术语表是锦上添花，失败不该阻断翻译
  }
  const out = {};
  for (const it of items || []) {
    const term = String(it?.term || "").trim();
    const rendering = String(it?.rendering || "").trim();
    if (term && rendering && term !== rendering) out[term] = rendering;
  }
  return out;
}

export function formatGlossary(mapping, limit = 40) {
  const entries = Object.entries(mapping || {}).slice(0, limit);
  if (!entries.length) return "";
  return "术语对照（必须严格遵守）：\n" + entries.map(([k, v]) => `${k} → ${v}`).join("\n");
}
