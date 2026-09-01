import { useRef, useState } from "react";

/** 难词模式下不呈现的块：与对照模式保持一致 */
const DROP = new Set(["header_footer", "watermark", "author"]);

/** 把整段文本按难词位置切成片段，只在难词处包一层标记 */
function segments(text, words) {
  if (!words?.length) return [{ text }];
  const out = [];
  let at = 0;
  for (const w of words) {
    if (w.start < at) continue;              // 位置重叠时以先到的为准
    if (w.start > at) out.push({ text: text.slice(at, w.start) });
    out.push({ text: text.slice(w.start, w.end), word: w });
    at = w.end;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

/** 取难词所在的句子，收藏时一并记下 */
function sentenceAround(text, start, end) {
  const left = Math.max(
    text.lastIndexOf(". ", start), text.lastIndexOf("\n", start), -1
  );
  let right = text.indexOf(". ", end);
  if (right < 0) right = text.length;
  return text.slice(left + 1, right + 1).trim();
}

export default function HardWordPane({
  paneRef, pages, hardwords, active, onPick, onScroll, collected, onCollect,
}) {
  const [card, setCard] = useState(null);
  const hideTimer = useRef(0);

  const show = (e, word, blockText) => {
    clearTimeout(hideTimer.current);
    const r = e.currentTarget.getBoundingClientRect();
    const pane = paneRef.current.getBoundingClientRect();
    setCard({
      word,
      context: sentenceAround(blockText, word.start, word.end),
      // 贴在词下方；靠近右边缘时向左收，避免溢出栏外
      left: Math.min(r.left - pane.left, pane.width - 300),
      top: r.bottom - pane.top + 6,
    });
  };
  const hide = () => {
    hideTimer.current = setTimeout(() => setCard(null), 160);
  };

  return (
    <div className="pane pane-zh hw-pane" ref={paneRef} onScroll={onScroll}>
      <div className="trans">
        {pages.map((p) => (
          <section key={p.page}>
            <div className="folio-rule">第 {p.page + 1} 页</div>
            {p.blocks
              .filter((b) => b.is_head && b.order >= 0 && !DROP.has(b.type))
              .map((b) => {
                const words = hardwords[b.id] || [];
                const kind =
                  b.type === "title" ? "en-title"
                  : b.type === "heading" ? "en-heading"
                  : b.type === "caption" || b.type === "reference" ? "en-small"
                  : "";
                return (
                  <div
                    key={b.id}
                    data-block={b.id}
                    className={"seg-block" + (b.id === active ? " is-active" : "")}
                    onMouseEnter={() => onPick(b.id, "zh")}
                    onClick={() => onPick(b.id, "zh", true)}
                  >
                    <p className={`en ${kind}`}>
                      {segments(b.text, words).map((s, i) =>
                        s.word ? (
                          <span
                            key={i}
                            className={
                              "hw" + (collected.has(s.word.lemma) ? " is-collected" : "")
                            }
                            onMouseEnter={(e) => show(e, s.word, b.text)}
                            onMouseLeave={hide}
                          >
                            {s.text}
                          </span>
                        ) : (
                          <span key={i}>{s.text}</span>
                        )
                      )}
                    </p>
                  </div>
                );
              })}
          </section>
        ))}
      </div>

      {card && (
        <div
          className="hw-card"
          style={{ left: card.left, top: card.top }}
          onMouseEnter={() => clearTimeout(hideTimer.current)}
          onMouseLeave={hide}
        >
          <div className="hw-head">
            <b>{card.word.lemma}</b>
            {card.word.phonetic && <span className="hw-ph">/{card.word.phonetic}/</span>}
          </div>
          <div className="hw-gloss">{card.word.gloss}</div>
          <div className="hw-meta">
            {card.word.coca ? `COCA 第 ${card.word.coca} 位` : "COCA 两万词以外"}
            {card.word.tag && ` · ${card.word.tag}`}
          </div>
          <button
            className="hw-add"
            onClick={() => onCollect(card.word, card.context)}
          >
            {collected.has(card.word.lemma) ? "已在生词本 · 移出" : "收进生词本"}
          </button>
        </div>
      )}
    </div>
  );
}
