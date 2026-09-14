/**
 * 块类型分类。
 *
 * 标题判定靠**字重而非字号**：实测 ACL 模板论文里 "4.4 Corpus analysis"
 * 字号 10.9 反而小于正文 11.0，只有 bold 是可靠信号。
 */
import { BlockType } from "./model.js";

const RE_CAPTION = /^\s*(Figure|Fig\.|Table|Algorithm|Listing|Appendix)\s*\d+/i;
const RE_LIST = /^\s*([•·▪‣∙]|[-–—]\s|\(?[a-z0-9]{1,3}[.)]\s)/;
const RE_BULLET = /^\s*[•·▪‣∙]/;
const RE_HEADING_NUM = /^\s*(\d+(\.\d+)*|[A-Z](\.\d+)*)\s*\.?\s+\S/;
const RE_REF_HEAD = /^\s*(References|Bibliography|参考文献)\s*$/i;
/** 附录/章节标题：字母或数字编号后跟空格与正文 */
const RE_SECTION_HEAD = /^\s*(Appendix\b|附录|[A-Z](\.\d+)*\s+\S|\d+(\.\d+)*\s+\S)/;

/** 跨页重复检测的取值带：页面上下各这么多比例 */
const RUNNING_BAND = 0.12;
/** 归一化后出现在这么多页上，才算书眉 */
const RUNNING_MIN_PAGES = 3;

/** 书眉的归一化键：去掉数字（页码会变），y 位置取粗粒度 */
function runningKey(text, y0) {
  return `${text.trim().toLowerCase().replace(/\d+/g, "#")}|${Math.round(y0 / 6)}`;
}

/**
 * 找出书眉与页脚：**同样的文字在同样的高度反复出现**。
 *
 * 只按「离页边多近」判断不可靠 —— 实测 ACM 模板的书眉在页高 7.7% 处，
 * ACL 模板的页码在 94% 处，任何固定阈值都会在另一种模板上失手。
 * 跨页重复才是书眉的定义性特征。
 */
export function findRunningHeads(pages) {
  const seen = new Map();
  for (const page of pages) {
    const top = page.height * RUNNING_BAND;
    const bottom = page.height * (1 - RUNNING_BAND);
    for (const b of page.blocks) {
      const text = b.text.trim();
      if (!text || text.length > 120) continue;
      if (b.bbox[1] > top && b.bbox[3] < bottom) continue;
      const key = runningKey(text, b.bbox[1]);
      if (!seen.has(key)) seen.set(key, []);
      seen.get(key).push(b);
    }
  }

  const out = new Set();
  const need = Math.min(RUNNING_MIN_PAGES, Math.max(2, Math.floor(pages.length / 3)));
  for (const blocks of seen.values()) {
    const hit = new Set(blocks.map((b) => b.page));
    // 纯数字（页码）只要落在带内就算，它每页都不一样，凑不齐重复次数
    const isNumber = blocks.every((b) => /^\d+$/.test(b.text.replace(/\s/g, "")));
    if (hit.size >= need || isNumber) for (const b of blocks) out.add(b.id);
  }
  return out;
}

function ratio(spans, key) {
  const total = spans.reduce((n, s) => n + s.text.length, 0) || 1;
  return spans.reduce((n, s) => n + (s[key] ? s.text.length : 0), 0) / total;
}

function classify(block, pageHeight, pageWidth, inReferences) {
  if (block.rotated) return BlockType.WATERMARK;   // 竖排文字必是侧边戳
  const [x0, y0, x1, y1] = block.bbox;
  const text = block.text.trim();
  const w = x1 - x0, h = y1 - y0;

  // 1. 水印：又窄又高的竖排块（arXiv 侧边戳），或贴在页面左右边缘外侧
  if (h > 3 * w && h > pageHeight * 0.25) return BlockType.WATERMARK;
  if (x1 < pageWidth * 0.08 || x0 > pageWidth * 0.92) return BlockType.WATERMARK;

  // 2. 页眉页脚：贴顶或贴底的短块
  if ((y0 > pageHeight * 0.93 || y1 < pageHeight * 0.07) && text.length < 120)
    return BlockType.HEADER_FOOTER;

  // 3. 参考文献区
  if (RE_REF_HEAD.test(text)) return BlockType.HEADING;
  if (inReferences) return BlockType.REFERENCE;

  // 4. 公式 / 代码：按 span 字体占比
  if (ratio(block.spans, "math") > 0.5) return BlockType.MATH;
  if (ratio(block.spans, "mono") > 0.6) return BlockType.CODE;

  if (RE_CAPTION.test(text)) return BlockType.CAPTION;
  // 以项目符号开头的行不可能是标题，这条要排在字重判定之前 ——
  // ACM 的 CCS 条目是加粗的项目符号行，否则会被当成标题
  if (RE_BULLET.test(text)) return BlockType.LIST;

  // 5. 章节标题：整块加粗 + 文本短。字号在此不可靠，故不参与判定。
  if (ratio(block.spans, "bold") > 0.7 && text.length < 120 && !text.includes("\n")) {
    if (RE_HEADING_NUM.test(text) || text.length < 60) return BlockType.HEADING;
  }

  if (RE_LIST.test(text)) return BlockType.LIST;
  return BlockType.BODY;
}

/**
 * 判断该块是否标志着参考文献区结束。
 *
 * 附录常常排在参考文献之后。若 inReferences 一经置位就再不复位，
 * 整个附录都会被当成文献跳过翻译 —— 实测这份论文有 8 页附录因此丢失。
 * 参考文献条目不加粗，而附录章节标题加粗且带编号，据此区分。
 */
function endsReferences(block) {
  const text = block.text.trim();
  return ratio(block.spans, "bold") > 0.7 && text.length < 120
    && RE_SECTION_HEAD.test(text);
}

/** 就地分类整页。返回离开本页时是否仍处于参考文献区。 */
export function classifyPage(blocks, pageHeight, pageWidth, inReferences, running) {
  running = running || new Set();
  for (const b of blocks) {
    if (b.type === BlockType.TABLE) continue;      // 表格已在管线中定型
    if (running.has(b.id)) {                       // 跨页重复的书眉/页码
      b.type = BlockType.HEADER_FOOTER;
      continue;
    }
    if (inReferences && endsReferences(b)) inReferences = false;
    b.type = classify(b, pageHeight, pageWidth, inReferences);
    if (b.type === BlockType.HEADING && RE_REF_HEAD.test(b.text.trim()))
      inReferences = true;
  }
  return inReferences;
}

/** 标注首页的标题与作者块。标题取首页最靠上的加粗大字块。 */
export function markFrontMatter(blocks) {
  const cand = blocks.filter(
    (b) => b.type === BlockType.BODY || b.type === BlockType.HEADING
  );
  if (!cand.length) return;
  const top = [...cand].sort((a, b) => a.bbox[1] - b.bbox[1]).slice(0, 6);
  const maxSize = Math.max(...top.map((b) => Math.max(0, ...b.spans.map((s) => s.size))));
  for (const b of top) {
    const size = Math.max(0, ...b.spans.map((s) => s.size));
    if (size >= maxSize - 0.1 && ratio(b.spans, "bold") > 0.5) b.type = BlockType.TITLE;
    else if (b.bbox[1] < 200 && b.type !== BlockType.TITLE) b.type = BlockType.AUTHOR;
  }
}
