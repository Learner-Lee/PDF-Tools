import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function VocabBook({ onClose, onChanged }) {
  const [items, setItems] = useState([]);
  const load = () => api.book().then((d) => setItems(d.items)).catch(() => {});
  useEffect(() => { load(); }, []);

  const remove = async (lemma) => {
    await api.removeWord(lemma);
    await load();
    onChanged?.();
  };

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label="生词本">
        <h2>生词本</h2>
        <p className="lede">
          {items.length ? `${items.length} 个词。` : "还没有收藏。在难词模式下点开释义卡片即可收进来。"}
        </p>

        {items.length > 0 && (
          <div className="book">
            {items.map((it) => (
              <div key={it.lemma} className="book-row">
                <div className="book-main">
                  <b>{it.surface || it.lemma}</b>
                  {it.phonetic && <span className="hw-ph">/{it.phonetic}/</span>}
                  <div className="book-gloss">{it.gloss}</div>
                  {it.context && <div className="book-ctx">{it.context}</div>}
                </div>
                <button className="icon-btn" onClick={() => remove(it.lemma)}>移出</button>
              </div>
            ))}
          </div>
        )}

        <div className="actions">
          <a className="btn btn-ghost" href={api.exportBookUrl("csv")} download>
            导出 CSV
          </a>
          <a className="btn btn-ghost" href={api.exportBookUrl("anki")} download>
            导出 Anki
          </a>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
        <p className="note">
          Anki 导入时选「字段由制表符分隔」，正面是单词，背面是音标、释义与例句。
        </p>
      </div>
    </div>
  );
}
