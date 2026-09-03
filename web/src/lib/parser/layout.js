/**
 * 栏检测与阅读顺序重建。
 *
 * 双栏论文里，原始块序碰巧常常是对的，但不可依赖 —— 一旦顺序错乱，
 * 译文会整篇错位。这里显式重建：先识别跨栏块（标题、宽表），
 * 用它们把页面切成横向条带，条带内再按 左栏自上而下 → 右栏自上而下 排序。
 */

const STRADDLE_TOL = 12;

/**
 * 判断页面是单栏还是双栏。
 *
 * 用文本量而非块数量：论文首页天然有一串跨栏块（标题、作者、单位、邮箱），
 * 按块数会把双栏首页误判成单栏，进而让右栏内容排到左栏前面。
 * 但这些块字数都很少，按文本量衡量就压不过双栏正文。
 */
export function detectColumns(blocks, pageWidth) {
  const body = blocks.filter(
    (b) => b.type !== "header_footer" && b.type !== "watermark"
  );
  if (body.length < 4) return 1;
  const mid = pageWidth / 2;
  const left = body.filter((b) => b.bbox[2] <= mid + STRADDLE_TOL);
  const right = body.filter((b) => b.bbox[0] >= mid - STRADDLE_TOL);
  const straddle = body.filter((b) => !left.includes(b) && !right.includes(b));

  if (left.length >= 2 && right.length >= 2) {
    const colChars = [...left, ...right].reduce((n, b) => n + b.text.length, 0);
    const strChars = straddle.reduce((n, b) => n + b.text.length, 0);
    if (colChars > strChars) return 2;
  }
  return 1;
}

/** 就地写入每个块的 column：0=左 1=右 -1=跨栏 */
export function assignColumns(blocks, pageWidth, columns) {
  if (columns === 1) {
    for (const b of blocks) b.column = 0;
    return;
  }
  const mid = pageWidth / 2;
  for (const b of blocks) {
    if (b.bbox[2] <= mid + STRADDLE_TOL) b.column = 0;
    else if (b.bbox[0] >= mid - STRADDLE_TOL) b.column = 1;
    else b.column = -1;
  }
}

/** 返回按阅读顺序排列的块，并就地写入 order。 */
export function readingOrder(blocks, columns) {
  const skip = blocks.filter(
    (b) => b.type === "header_footer" || b.type === "watermark"
  );
  const content = blocks.filter((b) => !skip.includes(b));
  let ordered;

  if (columns === 1) {
    ordered = [...content].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]);
  } else {
    const straddle = content.filter((b) => b.column === -1)
      .sort((a, b) => a.bbox[1] - b.bbox[1]);
    const colBlocks = content.filter((b) => b.column !== -1);
    ordered = [];
    let top = 0;
    // 跨栏块把页面切成条带：每个跨栏块之前的双栏内容自成一带
    for (const s of [...straddle, null]) {
      const bound = s ? s.bbox[1] : Infinity;
      const band = colBlocks.filter((b) => b.bbox[1] >= top && b.bbox[1] < bound);
      for (const col of [0, 1]) {
        ordered.push(
          ...band.filter((b) => b.column === col)
            .sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])
        );
      }
      if (s) { ordered.push(s); top = s.bbox[3]; }
    }
    // 兜底：任何因浮点边界漏掉的块按位置补回，绝不丢内容
    const missing = colBlocks.filter((b) => !ordered.includes(b));
    ordered.push(...missing.sort((a, b) => a.column - b.column || a.bbox[1] - b.bbox[1]));
  }

  ordered.forEach((b, i) => { b.order = i; });
  for (const b of skip) b.order = -1;
  return ordered;
}
