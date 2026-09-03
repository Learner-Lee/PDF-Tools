/**
 * 解析入口：PDF 文件 → 文档模型。全部在浏览器内完成，文件不离开本机。
 */
import { BlockType, applyTranslatePolicy } from "./model.js";
import {
  collectHyphenVocab, collectWords, detectLang, extractPage, joinLines, lineText,
} from "./extract.js";
import { assignColumns, detectColumns, readingOrder } from "./layout.js";
import { classifyPage, markFrontMatter } from "./classify.js";
import { mergeParagraphs, mergeReferences } from "./merge.js";
import { extractRules, findTables } from "./tables.js";

/** 平均每页可提取字符数低于此值，判定为扫描件，需 OCR（当前不支持） */
const TEXT_PDF_MIN_CHARS_PER_PAGE = 100;

function overlapRatio(inner, outer) {
  const w = Math.min(inner[2], outer[2]) - Math.max(inner[0], outer[0]);
  const h = Math.min(inner[3], outer[3]) - Math.max(inner[1], outer[1]);
  if (w <= 0 || h <= 0) return 0;
  const area = (inner[2] - inner[0]) * (inner[3] - inner[1]);
  return area > 0 ? (w * h) / area : 0;
}

function medianSize(pagesRaw) {
  const sizes = [];
  for (const raw of pagesRaw)
    for (const b of raw)
      for (const s of b.spans)
        if (s.text.trim()) sizes.push(Math.round(s.size * 10) / 10);
  if (!sizes.length) return 10;
  sizes.sort((a, b) => a - b);
  return sizes[Math.floor(sizes.length / 2)];
}

/**
 * @param {ArrayBuffer} data  PDF 字节
 * @param {object} opts
 * @param {object} opts.pdfjs  pdfjs 模块（由调用方注入，好让核心逻辑能在 Node 里测）
 * @param {(done:number,total:number)=>void} [opts.onProgress]
 */
export async function parsePdf(data, { pdfjs, onProgress } = {}) {
  const pdf = await pdfjs.getDocument({ data, useSystemFonts: false }).promise;
  const meta = await pdf.getMetadata().catch(() => ({}));

  // 先把所有页抽出来：连字符消歧需要全文词表，抽取与拼接必须分两趟
  const pagesRaw = [];
  const pageInfo = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const vp = page.getViewport({ scale: 1 });
    const raw = await extractPage(page, vp.width, vp.height);
    const opList = await page.getOperatorList();
    pagesRaw.push(raw);
    pageInfo.push({
      width: vp.width, height: vp.height,
      rules: extractRules(opList, pdfjs.OPS, vp.height),
      images: [],
    });
    onProgress?.(i, pdf.numPages);
  }

  const allLines = pagesRaw.flatMap((raw) => raw.flatMap((b) => b.lines));
  const totalChars = allLines.join("").trim().length;
  const isTextPdf = totalChars / Math.max(pdf.numPages, 1) >= TEXT_PDF_MIN_CHARS_PER_PAGE;

  const doc = {
    pageCount: pdf.numPages,
    isTextPdf,
    title: meta?.info?.Title || "",
    pages: [],
    pdf,                         // 留给 PdfPane 直接渲染，避免二次解析
  };
  if (!isTextPdf) return doc;

  const hyphenVocab = collectHyphenVocab(allLines);
  const words = collectWords(allLines);
  const bodySize = medianSize(pagesRaw);
  let inRefs = false;
  const globalOrder = [];

  for (let pno = 0; pno < pdf.numPages; pno++) {
    const info = pageInfo[pno];
    const raw = pagesRaw[pno];
    const page = { number: pno, width: info.width, height: info.height, columns: 1, blocks: [], images: [] };

    raw.forEach((rb, i) => {
      const text = joinLines(rb.lines, hyphenVocab, words);
      if (!text.trim()) return;
      page.blocks.push({
        id: `p${pno}b${String(i).padStart(2, "0")}`,
        page: pno,
        bbox: rb.bbox,
        type: BlockType.BODY,
        text,
        spans: rb.spans,
        column: 0,
        order: 0,
        lang: detectLang(text),
        rotated: !!rb.rotated,
        _col: rb.column,
        translate: true,
        mergedFrom: [],
        mergedInto: null,
        translation: null,
        table: null,
      });
    });

    // 表格：整块替换掉区域内的散落文本块，否则同样内容会重复出现
    findTables(info.rules, raw, hyphenVocab, words).forEach((tbl, ti) => {
      const inside = page.blocks.filter((b) => overlapRatio(b.bbox, tbl.bbox) >= 0.6);
      if (!inside.length) return;
      // 表格块的框取横线范围与实际文本范围的并集
      const bbox = [
        Math.min(tbl.bbox[0], ...inside.map((b) => b.bbox[0])),
        Math.min(tbl.bbox[1], ...inside.map((b) => b.bbox[1])),
        Math.max(tbl.bbox[2], ...inside.map((b) => b.bbox[2])),
        Math.max(tbl.bbox[3], ...inside.map((b) => b.bbox[3])),
      ];
      page.blocks = page.blocks.filter((b) => !inside.includes(b));
      page.blocks.push({
        id: `p${pno}t${ti}`, page: pno, bbox, type: BlockType.TABLE,
        text: tbl.rows.flat().filter(Boolean).join(" "),
        spans: [], column: 0, order: 0, lang: "en", translate: false,
        mergedFrom: [], mergedInto: null, translation: null,
        table: { rows: tbl.rows, headerRows: tbl.headerRows },
      });
    });

    inRefs = classifyPage(page.blocks, info.height, info.width, inRefs);
    if (pno === 0) markFrontMatter(page.blocks);

    // 栏号在抽取阶段已按 span 分布确定，比事后按块 bbox 重判更可靠
    const known = page.blocks.filter((b) => b._col !== undefined);
    page.columns = known.some((b) => b._col === 1) ? 2 : 1;
    for (const b of page.blocks) {
      b.column = b._col !== undefined ? b._col : 0;
      delete b._col;
    }
    globalOrder.push(...readingOrder(page.blocks, page.columns));
    doc.pages.push(page);
  }

  mergeParagraphs(globalOrder, hyphenVocab, words);
  mergeReferences(globalOrder, hyphenVocab, words);
  applyTranslatePolicy(doc, false);
  return doc;
}

/** 表格识别需要行级信息，从 span 重新聚一次行 */
function groupRawLines(spans) {
  const sorted = [...spans].sort((a, b) => a.baseline - b.baseline || a.bbox[0] - b.bbox[0]);
  const lines = [];
  for (const s of sorted) {
    const last = lines[lines.length - 1];
    if (last && Math.abs(last.baseline - s.baseline) <= Math.max(s.size, 6) * 0.3) {
      last.spans.push(s);
    } else lines.push({ baseline: s.baseline, spans: [s] });
  }
  for (const l of lines) {
    l.spans.sort((a, b) => a.bbox[0] - b.bbox[0]);
    l.bbox = [
      Math.min(...l.spans.map((s) => s.bbox[0])),
      Math.min(...l.spans.map((s) => s.bbox[1])),
      Math.max(...l.spans.map((s) => s.bbox[2])),
      Math.max(...l.spans.map((s) => s.bbox[3])),
    ];
  }
  return lines;
}

export { BlockType, applyTranslatePolicy };
export { blocks, translatable } from "./model.js";
