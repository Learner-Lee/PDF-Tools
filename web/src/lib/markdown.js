/** Markdown 导出：丢版式但内容完整、可二次编辑。 */
import { BlockType } from "./parser/model.js";

const RE_NUM = /^\s*(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\s+\S/;

function headingLevel(text) {
  const m = RE_NUM.exec(text);
  return m ? Math.min(2 + (m[1].split(".").length - 1), 6) : 2;
}

function tableMd(table) {
  const rows = table?.zh || table?.rows || [];
  if (!rows.length) return "";
  const ncol = Math.max(...rows.map((r) => r.length));
  const head = table.headerRows || 1;
  const line = (cells) =>
    "| " + [...cells, ...Array(ncol - cells.length).fill("")]
      .map((c) => String(c).replace(/\|/g, "\\|").trim()).join(" | ") + " |";
  return [
    ...rows.slice(0, head).map(line),
    "|" + Array(ncol).fill(" --- ").join("|") + "|",
    ...rows.slice(head).map(line),
  ].join("\n");
}

function renderBlock(b) {
  const text = (b.translation || b.text).trim();
  if (b.type === BlockType.TABLE) return tableMd(b.table);
  if (!text) return "";
  if (b.type === BlockType.TITLE) return `# ${text}`;
  if (b.type === BlockType.HEADING) return `${"#".repeat(headingLevel(text))} ${text}`;
  if (b.type === BlockType.CODE || b.type === BlockType.MATH)
    return "```\n" + b.text.trim() + "\n```";
  if (b.type === BlockType.CAPTION || b.type === BlockType.AUTHOR) return `*${text}*`;
  if (b.type === BlockType.REFERENCE) return `- ${text}`;
  if (b.type === BlockType.LIST)
    return "-*•".includes(text[0]) ? text : `- ${text.replace(/^[•· ]+/, "")}`;
  return text;
}

export function toMarkdown(doc, filename) {
  const lines = [`<!-- 由 PDF 对照导出：${doc.title || filename || ""} -->\n`];
  let prevRef = false;
  for (const page of doc.pages) {
    const ordered = page.blocks
      .filter((b) => b.order >= 0 && !b.mergedInto)
      .sort((a, b) => a.order - b.order);
    for (const b of ordered) {
      if (b.type === BlockType.HEADER_FOOTER || b.type === BlockType.WATERMARK) continue;
      const md = renderBlock(b);
      if (!md) continue;
      // 连续的参考文献条目之间不空行，成组呈现
      if (!(prevRef && b.type === BlockType.REFERENCE) && lines.length) lines.push("");
      lines.push(md);
      prevRef = b.type === BlockType.REFERENCE;
    }
  }
  return lines.join("\n").trim() + "\n";
}

export function download(filename, text, mime = "text/markdown;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
