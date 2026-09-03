import { useEffect, useRef, useState } from "react";

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
  const cardRef = useRef(null);

  // 点击其他地方或按 Esc 关闭。卡片改成点击触发后，必须给出明确的关闭方式。
  useEffect(() => {
    if (!card) return;
    const onDown = (e) => {
      if (!cardRef.current?.contains(e.target) && !e.target.closest(".hw-pair")) {
        setCard(null);
      }
    };
    const onKey = (e) => e.key === "Escape" && setCard(null);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [card]);

  const toggle = (e, word, blockText) => {
    e.stopPropagation();               // 否则会触发块级的对位跳转
    if (card?.word.start === word.start && card?.blockId === word._blockId) {
      return setCard(null);            // 再点一次收起
    }
    const el = paneRef.current;
    const r = e.currentTarget.getBoundingClientRect();
    const pane = el.getBoundingClientRect();
    // 卡片是栏内的绝对定位元素，坐标要用内容坐标而非视口坐标 ——
    // 少加 scrollTop 的话，只有栏停在顶部时位置才是对的。
    // 用内容坐标后卡片随内容滚动，始终贴着那个词。
    setCard({
      word,
      blockId: word._blockId,
      context: sentenceAround(blockText, word.start, word.end),
      left: Math.max(0, Math.min(r.left - pane.left + el.scrollLeft, el.clientWidth - 300)),
      top: r.bottom - pane.top + el.scrollTop + 6,
    });
  };

  return (
    <div className="pane pane-zh hw-pane" ref={paneRef} onScroll={onScroll}>
      <div className="trans">
        {pages.map((p) => (
          <section key={p.number}>
            <div className="folio-rule">第 {p.number + 1} 页</div>
            {p.blocks
              .filter((b) => !b.mergedInto && b.order >= 0 && !DROP.has(b.type))
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
                          // 点击区域包住原词与它的行内中文：
                          // 点中文是最自然的手势，不能反而把卡片关掉
                          <span
                            key={i}
                            className={
                              "hw-pair" +
                              (collected.has(s.word.lemma) ? " is-collected" : "")
                            }
                            role="button"
                            tabIndex={0}
                            aria-label={`${s.word.lemma}：${s.word.gloss}`}
                            onClick={(e) =>
                              toggle(e, { ...s.word, _blockId: b.id }, b.text)
                            }
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                toggle(e, { ...s.word, _blockId: b.id }, b.text);
                              }
                            }}
                          >
                            <span className="hw">{s.text}</span>
                            {s.word.brief && (
                              <span className="hw-zh">（{s.word.brief}）</span>
                            )}
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
          ref={cardRef}
          style={{ left: card.left, top: card.top }}
          onClick={(e) => e.stopPropagation()}
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
          <button className="hw-close" aria-label="关闭" onClick={() => setCard(null)}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
