/**
 * 从 pdf.js 的 text items 重建 span / 行 / 块。
 *
 * 与本地版（PyMuPDF）最大的差别：pdf.js **只给文本项，不给块**，
 * 行聚类与块切分要自己做。其余规则（空格修复、连字符消歧）是同一套 ——
 * 这些都是在真实论文上被数据推翻过一次才定下来的，见 DESIGN.md 附录 A。
 */

const RE_MONO = /Inconsolata|SFTT|Courier|Mono|Typewriter|CMTT/i;
/** 数学字体只认这几族。CMR/CMB 是 Computer Modern 正文体，
 *  论文里用来排编号列表，绝不能当公式排除掉。 */
const RE_MATH = /CM(MI|SY|EX)|MS[AB]M|EU[FSMB]|rsfs|stmary|LASY/i;
const RE_BOLD = /Bold|Medi|Black|Semib|Heavy/i;
const RE_ITALIC = /Ital|Oblique/i;
const RE_CJK = /[一-鿿㐀-䶿]/;
const RE_LATIN = /[A-Za-z]/;

/** pdf.js 的字体名带子集前缀（PJRSLU+NimbusRomNo9L-Medi），去掉它 */
function cleanFontName(name) {
  return String(name || "").replace(/^[A-Z]{6}\+/, "");
}

/**
 * 把 pdf.js 的 item 转成 span。
 *
 * pdf.js 的坐标原点在左下角，且 transform[5] 是基线位置；
 * 统一换算成左上角原点的字形外框，好和后续的行列聚类对齐。
 */
function toSpan(item, fontName, pageHeight) {
  const tx = item.transform;
  const size = Math.hypot(tx[1], tx[3]) || tx[3] || item.height || 10;
  const x0 = tx[4];
  const baseline = pageHeight - tx[5];
  // 竖排/旋转文字（arXiv 侧边戳）：pdf.js 给的是旋转后的变换矩阵，
  // 按水平文字算出的 bbox 完全不对，得单独标出来交给分类层当水印处理
  const rotated = Math.abs(tx[1]) > 0.01 || Math.abs(tx[2]) > 0.01;
  const w = item.width || 0;
  const bbox = rotated
    ? [x0 - size, baseline - w, x0 + size, baseline]
    : [x0, baseline - size * 0.8, x0 + w, baseline + size * 0.2];
  return {
    rotated,
    text: item.str,
    font: fontName,
    size: +size.toFixed(2),
    bold: RE_BOLD.test(fontName),
    italic: RE_ITALIC.test(fontName),
    mono: RE_MONO.test(fontName),
    math: RE_MATH.test(fontName),
    baseline,
    bbox,
  };
}

/** 取回真实字体名。必须先跑 getOperatorList，字体才会解析进 commonObjs。 */
async function fontMap(page, items) {
  const map = new Map();
  for (const it of items) {
    const id = it.fontName;
    if (!id || map.has(id)) continue;
    let name = id;
    try {
      const f = page.commonObjs.get(id);
      name = cleanFontName(f?.name) || id;
    } catch {
      /* 个别字体取不到就退回内部 id，只影响该块的样式判定 */
    }
    map.set(id, name);
  }
  return map;
}

/**
 * 先按栏切分 span，再聚行。
 *
 * 这一步是本地版（PyMuPDF 直接给块）没有的。双栏页面上左右栏同一高度的文字
 * **基线完全相同**，只按基线聚类会把两栏文字拼进同一行，得到
 * "Abstract frame comparison as participation in..." 这种东西。
 * 所以分栏必须在聚行之前。
 */
function findGutter(spans, pageWidth, pageHeight) {
  // 页面中段找一条无文字覆盖的竖直空白带。居中的作者行会横跨它 ——
  // 这正是要的：按单个 span 是否越过中线来分栏，会把居中行劈成两半。
  const step = 2;
  const n = Math.ceil(pageWidth / step);
  const cover = new Uint32Array(n);
  // 页码常常正落在栏间空白带正中（实测 x294.9~300.4），
  // 一个页码就足以让每一页都判成单栏，所以要先把页眉页脚区排除
  const topLimit = pageHeight * 0.07;
  const botLimit = pageHeight * 0.93;
  for (const s of spans) {
    if (s.rotated) continue;
    if (s.baseline < topLimit || s.baseline > botLimit) continue;
    const a = Math.max(0, Math.floor(s.bbox[0] / step));
    const b = Math.min(n - 1, Math.ceil(s.bbox[2] / step));
    for (let i = a; i <= b; i++) cover[i]++;
  }

  // 判据是中带覆盖**相对两侧栏**的比值，而非绝对空白：
  // 一两个跨栏元素（宽表、居中标题）不该让整页塌成单栏。
  // 实测真双栏页此比值为 0~26%，被宽表主导的页面则到 59%。
  const mean = (a, b) => {
    let sum = 0;
    for (let i = a; i < b; i++) sum += cover[i];
    return sum / Math.max(b - a, 1);
  };
  const sides = Math.min(
    mean(Math.floor(n * 0.15), Math.floor(n * 0.35)),
    mean(Math.floor(n * 0.65), Math.floor(n * 0.85))
  );
  if (sides < 3) return null;                 // 内容太少，判不出栏
  const thresh = sides * 0.35;

  const lo = Math.floor(n * 0.38), hi = Math.ceil(n * 0.62);
  let best = null, run = 0;
  for (let i = lo; i <= hi; i++) {
    if (cover[i] < thresh) {
      run++;
      if (!best || run > best.len) best = { end: i, len: run };
    } else run = 0;
  }
  // 空白带至少 8pt 宽才算栏间距，否则只是行末参差
  if (!best || best.len * step < 8) return null;
  return ((best.end - best.len / 2 + 0.5) * step);
}

function splitByColumn(spans, pageWidth, pageHeight) {
  const gutter = findGutter(spans, pageWidth, pageHeight);
  if (gutter === null) return [{ column: 0, spans }];

  // 先把同一基线上紧邻的 span 连成「行段」，再按行段整体分栏。
  // 居中的作者行由多个不跨中线的 span 组成，逐个判会被劈成左右两半；
  // 而栏间距（实测 14pt）远大于行内字距（<5pt），据此可以区分。
  const runs = [];
  for (const sp of [...spans].sort((a, b) => a.baseline - b.baseline || a.bbox[0] - b.bbox[0])) {
    const last = runs[runs.length - 1];
    const near = last
      && Math.abs(last.baseline - sp.baseline) <= Math.max(sp.size, 6) * 0.3
      && sp.bbox[0] - last.x1 <= Math.max(sp.size * 0.6, 5);
    if (near) {
      last.spans.push(sp);
      last.x1 = Math.max(last.x1, sp.bbox[2]);
    } else {
      runs.push({ baseline: sp.baseline, x0: sp.bbox[0], x1: sp.bbox[2], spans: [sp] });
    }
  }

  const tol = 2;
  const straddle = [], left = [], right = [];
  for (const r of runs) {
    if (r.x0 < gutter - tol && r.x1 > gutter + tol) straddle.push(...r.spans);
    else if (r.x1 <= gutter + tol) left.push(...r.spans);
    else right.push(...r.spans);
  }

  const chars = (xs) => xs.reduce((n, s) => n + s.text.length, 0);
  // 判据与本地版一致：按文本量而非条数，否则首页那串跨栏标题会压垮判断
  const twoCol = left.length >= 4 && right.length >= 4
    && chars(left) + chars(right) > chars(straddle);

  if (!twoCol) return [{ column: 0, spans }];
  return [
    { column: -1, spans: straddle },
    { column: 0, spans: left },
    { column: 1, spans: right },
  ].filter((g) => g.spans.length);
}

/** 同一基线上的 span 聚成一行 */
function groupLines(spans) {
  const sorted = [...spans].sort((a, b) => a.baseline - b.baseline || a.bbox[0] - b.bbox[0]);
  const lines = [];
  for (const s of sorted) {
    const last = lines[lines.length - 1];
    // 容差取字号的 30%：同一行的上下标基线会有小幅偏移
    if (last && Math.abs(last.baseline - s.baseline) <= Math.max(s.size, 6) * 0.3) {
      last.spans.push(s);
      last.baseline = (last.baseline * (last.spans.length - 1) + s.baseline) / last.spans.length;
    } else {
      lines.push({ baseline: s.baseline, spans: [s] });
    }
  }
  for (const l of lines) {
    l.spans.sort((a, b) => a.bbox[0] - b.bbox[0]);
    l.bbox = [
      Math.min(...l.spans.map((s) => s.bbox[0])),
      Math.min(...l.spans.map((s) => s.bbox[1])),
      Math.max(...l.spans.map((s) => s.bbox[2])),
      Math.max(...l.spans.map((s) => s.bbox[3])),
    ];
    l.size = median(l.spans.map((s) => s.size));
  }
  return lines;
}

function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

/**
 * 行聚成块。
 *
 * pdf.js 不给块，这一步是本地版没有的。判据：同一栏内相邻行的基线间距接近
 * 正常行距、左边界大体对齐、字号一致，就归为一块；否则断开。
 */
function groupBlocks(lines) {
  const out = [];
  let cur = null;
  for (const l of lines) {
    if (!cur) { cur = { lines: [l] }; continue; }
    const prev = cur.lines[cur.lines.length - 1];
    const pitch = l.baseline - prev.baseline;
    const expect = Math.max(l.size, prev.size) * 1.6;
    const sameCol = l.bbox[0] < prev.bbox[2] && l.bbox[2] > prev.bbox[0];
    const sameSize = Math.abs(l.size - prev.size) <= Math.max(l.size, prev.size) * 0.15;
    if (pitch > 0 && pitch <= expect && sameCol && sameSize) {
      cur.lines.push(l);
    } else {
      out.push(cur);
      cur = { lines: [l] };
    }
  }
  if (cur) out.push(cur);

  for (const b of out) {
    b.spans = b.lines.flatMap((l) => l.spans);
    b.bbox = [
      Math.min(...b.lines.map((l) => l.bbox[0])),
      Math.min(...b.lines.map((l) => l.bbox[1])),
      Math.max(...b.lines.map((l) => l.bbox[2])),
      Math.max(...b.lines.map((l) => l.bbox[3])),
    ];
  }
  return out;
}

/** 拼接一行内的 span，按 bbox 间距补回缺失的空格。 */
export function lineText(spans) {
  const out = [];
  let prev = null;
  for (const sp of spans) {
    if (prev) {
      const gap = sp.bbox[0] - prev.bbox[2];
      // 阈值取字号 15%：小于此为字距抖动，大于此才是真正的词间空格
      const threshold = 0.15 * Math.max(prev.size, 1);
      const prevCh = out.length ? out[out.length - 1].slice(-1) : "";
      const nextCh = sp.text.slice(0, 1);
      // 中文逐字成 span，字间距天然超阈值，插空格会得到 "AI最 新 排 行 榜"
      const bothCJK = RE_CJK.test(prevCh) && RE_CJK.test(nextCh);
      if (gap > threshold && out.length && !bothCJK &&
          !/[\s\-‐]$/.test(out[out.length - 1]) && !/^\s/.test(sp.text)) {
        out.push(" ");
      }
    }
    out.push(sp.text);
    prev = sp;
  }
  // PDF 内容流里 CJK 字之间常常带真实的空格字符（实测 "AI最 新 排 行 榜"），
  // 那是排版用的字距而非词间空格，拼回中文时必须剔除
  return out.join("").replace(/(?<=[一-鿿])[ \t]+(?=[一-鿿])/g, "");
}

const RE_COMPOUND = /[A-Za-z]+(?:-[A-Za-z]+)+/g;
const RE_TAIL_WORD = /([A-Za-z]+(?:-[A-Za-z]+)*)-$/;
const RE_HEAD_WORD = /^([A-Za-z]+)/;
const RE_WORD = /[A-Za-z]{2,}/g;
const WORDCHAR = new Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'");

/** 全文行内出现的连字符复合词，作为「这个连字符是真的」的证据 */
export function collectHyphenVocab(allLines) {
  const vocab = new Set();
  for (const ln of allLines) {
    const t = ln.replace(/\s+$/, "");
    for (const m of t.matchAll(RE_COMPOUND)) {
      // 只取行内的：行尾那个可能是断词，不能作为证据
      if (m.index + m[0].length < t.length) vocab.add(m[0].toLowerCase());
    }
  }
  return vocab;
}

/**
 * 全文出现过的独立英文单词。
 *
 * 必须剔除紧邻行尾连字符的碎片，否则词表会被它本该消歧的断词自己污染：
 * "Daphne Ip-" / "polito," 会让 ip 与 polito 双双进表，
 * 于是「两半各自成词」这条判据反过来把 Ippolito 判成了复合词。
 */
export function collectWords(allLines) {
  const words = new Set();
  let prevHyphenated = false;
  for (const ln of allLines) {
    const toks = [...ln.matchAll(RE_WORD)];
    const t = ln.replace(/\s+$/, "");
    const dropLast = t.endsWith("-") && t.length >= 2 && /[A-Za-z]/.test(t[t.length - 2]);
    toks.forEach((m, i) => {
      if (prevHyphenated && i === 0) return;
      if (dropLast && i === toks.length - 1) return;
      words.add(m[0].toLowerCase());
    });
    prevHyphenated = dropLast;
  }
  return words;
}

/**
 * 把以连字符结尾的 head 与 tail 接起来，判断该连字符是断词还是复合词。
 *
 * 三条判据依次尝试，顺序是实测定下来的：
 * 1. 去连字符后的形式本就是文档里的词 → 断词（Xiao-hongshu → Xiaohongshu）
 * 2. 整个复合词在文档别处出现过 → 真连字符（text-only）
 * 3. 断开的两半各自都成词 → 真连字符（mass|produce）；都不成词则断词（classi|fiers）
 */
export function stitchHyphen(head, tail, hyphenVocab, words) {
  const mTail = RE_TAIL_WORD.exec(head);
  const mHead = RE_HEAD_WORD.exec(tail);
  if (!mTail || !mHead) return head + tail;      // "Qwen3-" + "235B"

  const last = mTail[1].split("-").pop();
  if (words.has((last + mHead[1]).toLowerCase())) return head.slice(0, -1) + tail;
  if (hyphenVocab.has(`${mTail[1]}-${mHead[1]}`.toLowerCase())) return head + tail;
  if (words.has(last.toLowerCase()) && words.has(mHead[1].toLowerCase())) return head + tail;
  if (/^[a-z]/.test(tail)) return head.slice(0, -1) + tail;
  return head + tail;
}

/** 合并块内多行，处理行尾连字符断词。 */
export function joinLines(lines, hyphenVocab = new Set(), words = new Set()) {
  let out = "";
  for (const raw of lines) {
    const cur = raw.trim();
    if (!cur) continue;
    if (!out) { out = cur; continue; }
    if (out.endsWith("-") && out.length >= 2 && RE_LATIN.test(out[out.length - 2])) {
      out = stitchHyphen(out, cur, hyphenVocab, words);
    } else if (RE_CJK.test(out.slice(-1)) && RE_CJK.test(cur[0])) {
      out += cur;                                 // 中文之间不加空格
    } else {
      out += " " + cur;
    }
  }
  return out;
}

/** 按 CJK 字符占比判断块语言。中文块不该再被翻译一遍。 */
export function detectLang(text) {
  const stripped = text.replace(/\s/g, "");
  if (!stripped) return "en";
  const cjk = (stripped.match(new RegExp(RE_CJK.source, "g")) || []).length;
  const ratio = cjk / stripped.length;
  if (ratio > 0.3) return "zh";
  if (ratio > 0.05) return "mixed";     // 英文正文里嵌了中文词，仍需翻译
  return "en";
}

/** 抽取一页的原始块（未分类、未合并），并返回行文本供建词表用。 */
export async function extractPage(page, pageWidth, pageHeight) {
  await page.getOperatorList();          // 触发字体解析
  const tc = await page.getTextContent();
  const fonts = await fontMap(page, tc.items);

  const spans = tc.items
    .filter((it) => it.str && it.str.length)
    .map((it) => toSpan(it, fonts.get(it.fontName) || it.fontName, pageHeight))
    .filter((s) => s.text.trim() || s.text === " ");

  const out = [];
  const rotated = spans.filter((s) => s.rotated);
  const upright = spans.filter((s) => !s.rotated);
  if (rotated.length) {
    out.push({
      bbox: [
        Math.min(...rotated.map((s) => s.bbox[0])), Math.min(...rotated.map((s) => s.bbox[1])),
        Math.max(...rotated.map((s) => s.bbox[2])), Math.max(...rotated.map((s) => s.bbox[3])),
      ],
      spans: rotated, column: -1, rotated: true,
      lines: [rotated.map((s) => s.text).join("")], linesRaw: [],
    });
  }
  for (const grp of splitByColumn(upright, pageWidth, pageHeight)) {
    for (const b of groupBlocks(groupLines(grp.spans))) {
      out.push({
        bbox: b.bbox,
        spans: b.spans,
        column: grp.column,
        lines: b.lines.map((l) => lineText(l.spans)),
        linesRaw: b.lines,
      });
    }
  }
  return out;
}
