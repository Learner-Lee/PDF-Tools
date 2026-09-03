/**
 * 跨块、跨栏、跨页的段落合并，以及参考文献条目合并。
 *
 * 一个自然段常被切成多个块（"…three-way classi-" / "fiers. The primary…"），
 * 不合并就送去翻译，译文会被拦腰截断且语义丢失。
 */
import { BlockType } from "./model.js";
import { stitchHyphen } from "./extract.js";

const SENT_END = /[.!?;:。！？；：)\]}”’"']\s*$/;
const ENDS_HYPHEN = /[A-Za-z]-$/;
const STARTS_CONT = /^[a-z一-鿿),;:\]]/;
const MERGEABLE = new Set([BlockType.BODY, BlockType.LIST]);

/** 续行缩进超过首行这么多 pt，即判为同一条文献的续写 */
const HANGING_INDENT = 4;

function canMerge(prev, cur) {
  // 长标题被排版拆成多块，分别翻译会各自丢掉半句语义，必须先拼回整句
  if (prev.type === BlockType.TITLE && cur.type === BlockType.TITLE) return true;
  if (!MERGEABLE.has(prev.type) || cur.type !== BlockType.BODY) return false;
  if (prev.lang !== cur.lang) return false;
  const p = prev.text.replace(/\s+$/, ""), c = cur.text.replace(/^\s+/, "");
  if (!p || !c) return false;
  if (ENDS_HYPHEN.test(p) && /^[a-z]/.test(c)) return true;
  return !SENT_END.test(p) && STARTS_CONT.test(c);
}

function stitch(head, tail, hyphenVocab, words) {
  head = head.replace(/\s+$/, "");
  tail = tail.replace(/^\s+/, "");
  if (head.endsWith("-") && head.length >= 2 && /[A-Za-z0-9]/.test(head[head.length - 2]))
    return stitchHyphen(head, tail, hyphenVocab, words);
  if (head && tail && /[一-鿿]/.test(head.slice(-1))) return head + tail;
  return head + " " + tail;
}

/** 就地合并。ordered 必须是全文阅读顺序（跨页连续）。 */
export function mergeParagraphs(ordered, hyphenVocab, words) {
  let head = null;
  for (const blk of ordered) {
    if (head && canMerge(head, blk)) {
      head.text = stitch(head.text, blk.text, hyphenVocab, words);
      head.mergedFrom.push(blk.id);
      blk.mergedInto = head.id;
      blk.translate = false;
      continue;
    }
    head = blk;
  }
}

/**
 * 把悬挂缩进的参考文献条目并成一条。
 *
 * 文献表用悬挂缩进排版：每条首行齐左，续行缩进。切成独立块后，一条文献变成
 * "Helmut Appel, …Crusius." 与 "2016. The interplay between…" 两块 ——
 * 分开翻译会把作者与标题割裂。按每栏内文献块的最左位置识别首行。
 */
export function mergeReferences(ordered, hyphenVocab, words) {
  const refs = ordered.filter((b) => b.type === BlockType.REFERENCE);
  if (!refs.length) return;

  // 跨栏、跨页续写的缩进量不同，必须按（页, 栏）分组求最左位置
  const flush = new Map();
  for (const b of refs) {
    const key = `${b.page}:${b.column}`;
    flush.set(key, Math.min(flush.get(key) ?? b.bbox[0], b.bbox[0]));
  }

  // 跨栏/跨页续写只可能发生在「上一组的最后一块 → 下一组的第一块」。
  // 不加这个约束，右栏第一条缩进的续行会被并进左栏最后一条文献，
  // 拼出 "…Daphne Ip-Annual Meeting of the Association…" 这种串行。
  const groupOf = (b) => `${b.page}:${b.column}`;
  const lastOf = new Map(), firstOf = new Map();
  for (const b of refs) {
    if (!firstOf.has(groupOf(b))) firstOf.set(groupOf(b), b.id);
    lastOf.set(groupOf(b), b.id);
  }

  let head = null;
  for (const b of ordered) {
    if (b.type !== BlockType.REFERENCE) { head = null; continue; }
    const left = flush.get(groupOf(b));
    const sameGroup = head && groupOf(head) === groupOf(b);
    const flowsOn = head && !sameGroup
      && lastOf.get(groupOf(head)) === head.id && firstOf.get(groupOf(b)) === b.id;
    if (head && (sameGroup || flowsOn) && left !== undefined
        && b.bbox[0] > left + HANGING_INDENT) {
      head.text = stitch(head.text, b.text, hyphenVocab, words);
      head.mergedFrom.push(b.id);
      b.mergedInto = head.id;
      b.translate = false;
    } else {
      head = b;
    }
  }
}
