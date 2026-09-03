/**
 * 难词判定。判定只回答「这个词对你难不难」，释义来自词库（离线、免费）。
 */
import { tokenize } from "./db.js";

/** 考试词表由易到难。选定某一级即认为掌握该级及以下的全部词汇。 */
export const EXAM_ORDER = ["zk", "gk", "cet4", "cet6", "ky", "ielts", "toefl", "gre"];
export const EXAM_LABELS = {
  zk: "中考", gk: "高考", cet4: "四级", cet6: "六级",
  ky: "考研", ielts: "雅思", toefl: "托福", gre: "GRE",
};
export const COCA_TIERS = [3000, 5000, 8000, 15000];

/**
 * 各考试等级对应的词频底线。
 * 考试大纲只覆盖两万词里的一小部分，没打标签的常用词（participation…）
 * 若一律算难词，标注会淹没正文。用词频兜住这批词。
 */
const EXAM_COCA_FLOOR = {
  zk: 1500, gk: 2500, cet4: 3500, cet6: 5000,
  ky: 6000, ielts: 6500, toefl: 7500, gre: 10000,
};

/** 功能词与极高频词，无论哪种基准都不该标记 */
const ALWAYS_KNOWN = new Set(`a an the and or but if of to in on at by for with from as
is are was were be been being am do does did have has had will would can could shall
should may might must not no this that these those it its he she they them we us you i
me my our their his her there here when where which who whom whose what how why all any
some such than then so too very more most also only other each both into over under
between about after before while during up out off down again further s t d ll re ve`
  .split(/\s+/));

const MIN_LEN = 3;
const RE_VOWEL = /[aeiouy]/;

export function knownExams(level) {
  const i = EXAM_ORDER.indexOf(level);
  return i < 0 ? new Set() : new Set(EXAM_ORDER.slice(0, i + 1));
}

function isDifficult(entry, profile) {
  if (!entry) return true;                    // 词库没收录，必然生僻
  if (profile.basis === "exam") {
    const floor = EXAM_COCA_FLOOR[profile.examLevel] ?? 5000;
    if (entry.coca && entry.coca <= floor) return false;
    const known = knownExams(profile.examLevel);
    return !entry.tag.split(/\s+/).some((t) => known.has(t));
  }
  // COCA 基准：名次在阈值内算认识；两万开外没有名次，一律算难
  return !entry.coca || entry.coca > profile.cocaTier;
}

/**
 * 找出一段文本里的难词。
 * @param {Set<string>} [skip] 术语表与专有名词等不需要标记的词
 */
export function analyze(text, profile, db, skip) {
  if (!db?.available) return [];
  skip = skip || new Set();
  const known = new Set(profile.known || []);
  const out = [];
  const seen = new Set();

  for (const [start, end, surface] of tokenize(text)) {
    const low = surface.toLowerCase();
    if (low.length < MIN_LEN || ALWAYS_KNOWN.has(low)) continue;
    if (!RE_VOWEL.test(low)) continue;         // 多半是切分残渣（Jablo´nska → nska）
    // 句中大写多为专有名词，不该当难词
    if (surface[0] === surface[0].toUpperCase() && /[A-Za-z]/.test(surface[0])
        && start > 0 && !".!?\n".includes(text[start - 1])) continue;

    const lemma = db.lemma(low);
    if (!lemma || ALWAYS_KNOWN.has(lemma) || known.has(lemma) || skip.has(lemma)) continue;
    if (seen.has(lemma)) continue;             // 同一段内同一个词只标一次

    const entry = db.get(lemma);
    if (!isDifficult(entry, profile)) continue;
    // 给不出释义就不标记：点开是空的下划线只会打断阅读
    if (!entry?.gloss) continue;

    seen.add(lemma);
    out.push({
      start, end, surface, lemma,
      phonetic: entry.phonetic, pos: entry.pos,
      gloss: entry.gloss, brief: entry.brief,
      coca: entry.coca, tag: entry.tag,
    });
  }
  return out;
}
