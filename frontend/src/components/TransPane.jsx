/** 右栏完全不呈现的块：纯噪音，出现反而干扰 */
const DROP = new Set(["header_footer", "watermark"]);

/** 表格：保住行列结构，逐格显示译文；未译的格子（纯数字）显示原文 */
function TableView({ table }) {
  if (!table?.rows?.length) return null;
  const rows = table.zh || table.rows;
  const head = table.header_rows || 1;
  return (
    <div className="table-wrap">
      <table className="zh-table">
        {head > 0 && (
          <thead>
            {rows.slice(0, head).map((r, i) => (
              <tr key={i}>{r.map((c, j) => <th key={j}>{c}</th>)}</tr>
            ))}
          </thead>
        )}
        <tbody>
          {rows.slice(head).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Body({ block }) {
  if (block.type === "table") return <TableView table={block.table} />;
  if (!block.translate) {
    // 公式、代码、以及原本就是中文的段落：原样保留，但仍占位，
    // 否则左右两栏会在这些地方失去对应关系
    return <p className="as-is">{block.text}</p>;
  }
  if (!block.translation) {
    return (
      <>
        <span className="pending" aria-label="翻译中" />
        <span className="pending" />
      </>
    );
  }
  const kind =
    block.type === "title" ? "zh-title"
    : block.type === "heading" ? "zh-heading"
    : block.type === "caption" ? "zh-caption"
    : block.type === "author" ? "zh-author"
    : "";
  return <p className={`zh ${kind}`}>{block.translation}</p>;
}

/**
 * 把连续的参考文献折叠成一条。
 *
 * 参考文献按设定不翻译，但整段丢掉会让两栏在文献页彻底失去对应 ——
 * 这份 19 页论文里有 258 个文献块，右栏会空掉好几页。折叠成一条标记，
 * 既不翻译也不占版面，位置对应仍在。
 */
function layout(blocks) {
  const out = [];
  let refs = null;
  for (const b of blocks) {
    if (b.type === "reference") {
      if (!refs) { refs = { kind: "refs", id: b.id, count: 0 }; out.push(refs); }
      refs.count += 1;
      continue;
    }
    refs = null;
    out.push({ kind: "block", id: b.id, block: b });
  }
  return out;
}

export default function TransPane({ paneRef, pages, active, onPick, onScroll }) {
  return (
    <div className="pane pane-zh" ref={paneRef} onScroll={onScroll}>
      <div className="trans">
        {pages.map((p) => (
          <section key={p.page}>
            <div className="folio-rule">第 {p.page + 1} 页</div>
            {layout(
              p.blocks.filter((b) => b.is_head && b.order >= 0 && !DROP.has(b.type))
            ).map((item) =>
              item.kind === "refs" ? (
                <div key={item.id} data-block={item.id} className="refs-mark">
                  参考文献 · {item.count} 条 · 按设定不翻译
                </div>
              ) : (
                <div
                  key={item.id}
                  data-block={item.id}
                  className={"seg-block" + (item.id === active ? " is-active" : "")}
                  onMouseEnter={() => onPick(item.id, "zh")}
                  onClick={() => onPick(item.id, "zh", true)}
                >
                  <Body block={item.block} />
                </div>
              )
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
