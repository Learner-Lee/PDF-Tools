import { useEffect, useRef, useState } from "react";

/**
 * 对位带：把当前段落在左栏的纵向跨度，与它在右栏的跨度连起来。
 *
 * 中文排版长度约为英文的 0.6~0.8 倍，两侧几何上永远对不齐 —— 这正是
 * 对照阅读最容易丢失位置的地方。这条带子把「对应但不等长」直接画出来：
 * 连接线的收窄程度就是两种语言的长度差。
 */
export default function Gutter({ enPane, zhPane, active }) {
  const hostRef = useRef(null);
  const [geom, setGeom] = useState(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let raf = 0;

    const measure = () => {
      raf = 0;
      const en = enPane.current?.querySelector(`[data-block="${CSS.escape(active || "")}"]`);
      const zh = zhPane.current?.querySelector(`[data-block="${CSS.escape(active || "")}"]`);
      if (!active || !en || !zh) return setGeom(null);

      const box = host.getBoundingClientRect();
      const a = en.getBoundingClientRect();
      const b = zh.getBoundingClientRect();
      // 两端都被各自栏的可视区裁剪，超出部分不该画出来
      const ea = enPane.current.getBoundingClientRect();
      const eb = zhPane.current.getBoundingClientRect();
      const clip = (r, c) => ({
        top: Math.max(r.top, c.top) - box.top,
        bottom: Math.min(r.bottom, c.bottom) - box.top,
      });
      const L = clip(a, ea);
      const R = clip(b, eb);
      if (L.bottom <= L.top || R.bottom <= R.top) return setGeom(null);
      setGeom({ L, R, h: box.height, w: box.width });
    };

    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();

    const panes = [enPane.current, zhPane.current].filter(Boolean);
    panes.forEach((p) => p.addEventListener("scroll", schedule, { passive: true }));
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    panes.forEach((p) => ro.observe(p));
    return () => {
      cancelAnimationFrame(raf);
      panes.forEach((p) => p.removeEventListener("scroll", schedule));
      window.removeEventListener("resize", schedule);
      ro.disconnect();
    };
  }, [enPane, zhPane, active]);

  if (!geom) return <div className="gutter" ref={hostRef} />;

  const { L, R, w } = geom;
  const pad = 3;
  const x0 = pad;
  const x1 = w - pad;
  const mid = w / 2;
  // 上下缘各一条曲线，围成一个随长度差收窄的带子
  const d =
    `M ${x0} ${L.top} C ${mid} ${L.top}, ${mid} ${R.top}, ${x1} ${R.top} ` +
    `L ${x1} ${R.bottom} C ${mid} ${R.bottom}, ${mid} ${L.bottom}, ${x0} ${L.bottom} Z`;

  return (
    <div className="gutter" ref={hostRef}>
      <svg aria-hidden="true">
        <path d={d} fill="var(--mark-wash)" />
        <path d={`M ${x0} ${L.top} C ${mid} ${L.top}, ${mid} ${R.top}, ${x1} ${R.top}`}
              fill="none" stroke="var(--mark)" strokeWidth="1" opacity="0.65" />
        <path d={`M ${x0} ${L.bottom} C ${mid} ${L.bottom}, ${mid} ${R.bottom}, ${x1} ${R.bottom}`}
              fill="none" stroke="var(--mark)" strokeWidth="1" opacity="0.65" />
        <line x1={x0} y1={L.top} x2={x0} y2={L.bottom}
              stroke="var(--mark)" strokeWidth="2" />
        <line x1={x1} y1={R.top} x2={x1} y2={R.bottom}
              stroke="var(--mark)" strokeWidth="2" />
      </svg>
    </div>
  );
}
