/** 文档模型：解析层的输出，也是翻译层与导出层的共同输入。 */

export const BlockType = {
  TITLE: "title",
  AUTHOR: "author",
  HEADING: "heading",
  BODY: "body",
  LIST: "list",
  CAPTION: "caption",
  CODE: "code",
  MATH: "math",
  TABLE: "table",
  REFERENCE: "reference",
  HEADER_FOOTER: "header_footer",
  WATERMARK: "watermark",
};

/** 永不翻译，与设置无关 */
export const NO_TRANSLATE = new Set([
  BlockType.CODE,
  BlockType.MATH,
  BlockType.HEADER_FOOTER,
  BlockType.WATERMARK,
  BlockType.TABLE,
]);

/**
 * 按当前设置重算每个块是否翻译。
 * 与解析分开，是为了让「翻译参考文献」这类开关能对已解析的文档立即生效。
 */
export function applyTranslatePolicy(doc, translateReferences) {
  for (const b of blocks(doc)) {
    if (b.mergedInto) b.translate = false;
    else if (b.type === BlockType.REFERENCE)
      b.translate = translateReferences && b.lang !== "zh";
    else b.translate = !NO_TRANSLATE.has(b.type) && b.lang !== "zh";
  }
}

export function* blocks(doc) {
  for (const p of doc.pages) yield* p.blocks;
}

export function translatable(doc) {
  return [...blocks(doc)].filter((b) => b.translate && b.text.trim());
}
