import { useEffect, useRef, useState } from "react";

/** 只有这些块参与对位；页眉页脚、水印不该抢焦点 */
const SKIP = new Set(["header_footer", "watermark"]);

function PageCanvas({ pdf, page, scale, active, onPick }) {
  const hostRef = useRef(null);
  const canvasRef = useRef(null);
  const [near, setNear] = useState(false);
  const [failed, setFailed] = useState(false);
  const w = page.width * scale;
  const h = page.height * scale;

  // 只渲染视口附近的页：一次性全渲染会卡住主线程
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) setNear(true); },
      { root: el.closest(".pane"), rootMargin: "800px 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!near || !pdf) return;
    let cancelled = false;
    let task = null;

    (async () => {
      const p = await pdf.getPage(page.number + 1);
      if (cancelled) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const vp = p.getViewport({ scale: scale * dpr });

      // 渲染到离屏画布，成功后整幅贴回：同一画布并发 render 会被 pdf.js 拒绝，
      // 而设置 canvas.width 会清空画面，渲染中途被取消就留一张白纸。
      const off = document.createElement("canvas");
      off.width = vp.width;
      off.height = vp.height;
      try {
        task = p.render({ canvasContext: off.getContext("2d"), viewport: vp });
        await task.promise;
      } catch (err) {
        if (err?.name !== "RenderingCancelledException" && !cancelled) setFailed(true);
        return;
      }
      if (cancelled) return;
      const cv = canvasRef.current;
      if (!cv) return;
      cv.width = off.width;
      cv.height = off.height;
      cv.style.width = `${w}px`;
      cv.style.height = `${h}px`;
      cv.getContext("2d").drawImage(off, 0, 0);
      setFailed(false);
    })();

    return () => { cancelled = true; task?.cancel?.(); };
  }, [near, pdf, page.number, scale, w, h]);

  return (
    <div className="page-wrap" ref={hostRef} style={{ width: w, height: h }}
         data-page={page.number}>
      <canvas ref={canvasRef} style={{ width: w, height: h }} />
      {failed && <div className="page-failed">第 {page.number + 1} 页渲染失败</div>}
      {page.blocks.map((b) => {
        const skip = SKIP.has(b.type);
        return (
          <div
            key={b.id}
            data-block={b.mergedInto || b.id}
            className={"blockbox" + (skip ? " is-skip" : "")
              + (!skip && (b.mergedInto || b.id) === active ? " is-active" : "")}
            style={{
              left: b.bbox[0] * scale, top: b.bbox[1] * scale,
              width: (b.bbox[2] - b.bbox[0]) * scale,
              height: (b.bbox[3] - b.bbox[1]) * scale,
            }}
            onMouseEnter={() => !skip && onPick(b.mergedInto || b.id, "en")}
            onClick={() => !skip && onPick(b.mergedInto || b.id, "en", true)}
          />
        );
      })}
    </div>
  );
}

export default function PdfPane({ paneRef, pdf, pages, active, onPick, onScroll }) {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = paneRef.current;
    if (!el || !pages.length) return;
    const fit = () => setScale(Math.min(1.7, (el.clientWidth - 56) / pages[0].width));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [paneRef, pages]);

  return (
    <div className="pane pane-en" ref={paneRef} onScroll={onScroll}>
      {pages.map((p) => (
        <PageCanvas key={p.number} pdf={pdf} page={p} scale={scale}
                    active={active} onPick={onPick} />
      ))}
    </div>
  );
}
