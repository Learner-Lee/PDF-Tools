/**
 * 表格识别。
 *
 * 学术论文用 booktabs 风格：只有横线，没有竖线与完整网格。
 * 按其实际结构还原：一组 x 范围相同的横线界定一张表，首尾横线之间的文本
 * 按 y 聚成行、按 x 区间合并成列，第一条中线以上为表头。
 */
import { lineText, stitchHyphen } from "./extract.js";

const RULE_MAX_H = 3;
const RULE_MIN_W = 40;
/** 同一张表的横线由排版引擎一次画出，端点完全一致。
 *  放宽到 12pt 会把同页上下相邻的两张表并成一张。 */
const RULE_X_TOL = 2.5;
const ROW_TOL = 3;
/** 一个格子里出现这么多个独立数值，说明列切分失真 */
const GARBLED_NUMS = 3;
const RE_NUM = /(?<![\w.])[-−–]?\d+(?:[.,]\d+)?%?(?![\w])/g;

function mul(m, n) {
  return [
    m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}
function apply(m, x, y) {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/**
 * 从 pdf.js 的算子流里提取横线。
 *
 * 本地版用 PyMuPDF 的 get_drawings() 直接拿矩形；这里要自己走算子流并维护
 * 变换矩阵栈，才能把路径坐标换算成页面坐标。
 */
export function extractRules(opList, OPS, pageHeight) {
  const rules = [];
  let ctm = [1, 0, 0, 1, 0, 0];
  const stack = [];
  let pending = null;

  for (let i = 0; i < opList.fnArray.length; i++) {
    const op = opList.fnArray[i];
    const args = opList.argsArray[i];
    if (op === OPS.save) stack.push([...ctm]);
    else if (op === OPS.restore) ctm = stack.pop() || [1, 0, 0, 1, 0, 0];
    else if (op === OPS.transform) ctm = mul(ctm, args);
    else if (op === OPS.constructPath) {
      const mm = args[2];                       // [minX, minY, maxX, maxY]
      if (mm && mm.length === 4) pending = mm;
    } else if ((op === OPS.stroke || op === OPS.fill || op === OPS.eoFill) && pending) {
      const [ax, ay] = apply(ctm, pending[0], pending[1]);
      const [bx, by] = apply(ctm, pending[2], pending[3]);
      const x0 = Math.min(ax, bx), x1 = Math.max(ax, bx);
      const yTop = pageHeight - Math.max(ay, by);
      const yBot = pageHeight - Math.min(ay, by);
      if (yBot - yTop <= RULE_MAX_H && x1 - x0 >= RULE_MIN_W)
        rules.push({ x0, y0: yTop, x1, y1: yBot });
      pending = null;
    }
  }
  return rules.sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
}

/** 按左右端点把横线分组，每组对应一张表 */
function groupRules(rules) {
  const groups = [];
  for (const r of rules) {
    const g = groups.find(
      (g) => Math.abs(g[0].x0 - r.x0) <= RULE_X_TOL && Math.abs(g[0].x1 - r.x1) <= RULE_X_TOL
    );
    if (g) g.push(r); else groups.push([r]);
  }
  return groups.filter((g) => g.length >= 2);   // 至少上下两条线才算表
}

/** 区域内的单元格：行内按空隙切分 */
function cellsIn(rawBlocks, box) {
  const [x0, top, x1, bot] = box;
  const out = [];
  for (const b of rawBlocks) {
    for (const line of b.linesRaw || []) {
      const [lx0, ly0, lx1, ly1] = line.bbox;
      if (!(top - 2 <= ly0 && ly1 <= bot + 2 && lx0 >= x0 - 6 && lx1 <= x1 + 6)) continue;
      const spans = line.spans.filter((s) => s.text.trim());
      if (!spans.length) continue;
      const groups = [];
      let cur = [spans[0]];
      for (const s of spans.slice(1)) {
        // 间隙超过约一个字宽即视为跨到下一格
        if (s.bbox[0] - cur[cur.length - 1].bbox[2] > 0.9 * Math.max(s.size, 1)) {
          groups.push(cur); cur = [s];
        } else cur.push(s);
      }
      groups.push(cur);
      for (const cell of groups) {
        const text = lineText(cell).trim();
        if (text) out.push({ y: ly0, x0: cell[0].bbox[0], x1: cell[cell.length - 1].bbox[2], text });
      }
    }
  }
  return out;
}

/**
 * 把所有单元格的 x 区间合并成列。
 * 表头常左对齐、数据常居中，同列区间不相等但必然重叠；不同列之间有干净空隙。
 */
function columns(cells) {
  const spans = cells.map((c) => [c.x0, c.x1]).sort((a, b) => a[0] - b[0]);
  const cols = [];
  for (const [a, b] of spans) {
    if (cols.length && a <= cols[cols.length - 1][1])
      cols[cols.length - 1][1] = Math.max(cols[cols.length - 1][1], b);
    else cols.push([a, b]);
  }
  return cols;
}

/** 把换行续写的行并回上一行 */
function mergeWrapped(grid, header, hyphenVocab, words) {
  const out = [];
  let newHeader = header;
  grid.forEach((row, i) => {
    // 首列自身也可能折行（"Persona-" / "primed"），以连字符结尾即是续写
    const headWrapped = out.length > 0 && /-\s*$/.test(out[out.length - 1][0]);
    const isCont = out.length && (!row[0].trim() || headWrapped)
      && row.some((c) => c.trim()) && i >= header;
    if (isCont) {
      row.forEach((cell, j) => {
        if (!cell.trim()) return;
        const prev = out[out.length - 1][j];
        if (!prev) out[out.length - 1][j] = cell;
        else if (/-$/.test(prev.replace(/\s+$/, "")))
          out[out.length - 1][j] = stitchHyphen(prev.replace(/\s+$/, ""), cell.replace(/^\s+/, ""), hyphenVocab, words);
        else out[out.length - 1][j] = prev + " " + cell;
      });
    } else {
      out.push([...row]);
      if (i < header) newHeader = out.length;
    }
  });
  return [out, Math.min(newHeader, Math.max(out.length - 1, 1))];
}

/**
 * 识别不准时退回普通文本。
 * 与其摆一张错位的表误导阅读，不如让内容以段落形式出现。
 */
function isMeaningful(rows) {
  if (rows.length < 2) return false;
  const ncol = Math.max(...rows.map((r) => r.length));
  if (ncol < 2) return false;
  const filled = rows.reduce((n, r) => n + r.filter((c) => c.trim()).length, 0);
  if (filled / (rows.length * ncol) < 0.5) return false;
  // 数值表里一格塞进多个数，是列没切开的信号
  for (const row of rows.slice(1))
    for (const cell of row)
      if ((cell.match(RE_NUM) || []).length >= GARBLED_NUMS) return false;
  return true;
}

export function findTables(rules, rawBlocks, hyphenVocab, words) {
  const out = [];
  for (const group of groupRules(rules)) {
    group.sort((a, b) => a.y0 - b.y0);
    const top = group[0].y0, bot = group[group.length - 1].y1;
    const x0 = Math.min(...group.map((r) => r.x0));
    const x1 = Math.max(...group.map((r) => r.x1));
    const cells = cellsIn(rawBlocks, [x0, top, x1, bot]);
    if (cells.length < 4) continue;
    const cols = columns(cells);
    if (cols.length < 2) continue;

    const rowsByY = [];
    for (const c of [...cells].sort((a, b) => a.y - b.y || a.x0 - b.x0)) {
      const last = rowsByY[rowsByY.length - 1];
      if (last && Math.abs(last.y - c.y) <= ROW_TOL) last.items.push(c);
      else rowsByY.push({ y: c.y, items: [c] });
    }

    let grid = rowsByY.map(({ items }) => {
      const row = new Array(cols.length).fill("");
      for (const it of items) {
        let best = 0, bestOv = -Infinity;
        cols.forEach(([a, b], i) => {
          const ov = Math.min(it.x1, b) - Math.max(it.x0, a);
          if (ov > bestOv) { bestOv = ov; best = i; }
        });
        row[best] = row[best] ? `${row[best]} ${it.text}` : it.text;
      }
      return row;
    });

    const midY = group.length >= 3 ? group[1].y0 : null;
    // booktabs 表格几乎不会有超过两行表头，多出来必是识别偏了
    let header = midY === null ? 1
      : Math.max(1, rowsByY.filter((r) => r.y < midY).length);
    header = Math.min(header, 2, Math.max(grid.length - 1, 1));
    [grid, header] = mergeWrapped(grid, header, hyphenVocab, words);

    if (isMeaningful(grid))
      out.push({ bbox: [x0, top, x1, bot], rows: grid, headerRows: header });
  }
  return out;
}
