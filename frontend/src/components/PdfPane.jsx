import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/** 只有这些块参与对位；页眉页脚、水印不该抢焦点 */
const SKIP = new Set(["header_footer", "watermark"]);

function PageCanvas({ pdf, page, scale, active, onPick }) {
  const hostRef = useRef(null);
  const canvasRef = useRef(null);
  const [near, setNear] = useState(false);
  const [failed, setFailed] = useState(false);
  const w = page.width * scale;
  const h = page.height * scale;

  // 只渲染视口附近的页：19 页论文若一次性全渲染会卡住主线程
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => e.isIntersecting && setNear(true),
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
      const p = await pdf.getPage(page.page + 1);
      if (cancelled) return;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const vp = p.getViewport({ scale: scale * dpr });

      // 渲染到离屏画布，成功后整幅贴回。
      // 直接渲染到可见画布有两个坑：同一画布并发 render 会被 pdf.js 拒绝；
      // 而设置 canvas.width 会清空画面，渲染中途被取消就永久留一张白纸。
      const off = document.createElement("canvas");
      off.width = vp.width;
      off.height = vp.height;

      try {
        task = p.render({ canvasContext: off.getContext("2d"), viewport: vp });
        await task.promise;
      } catch (err) {
        if (err?.name !== "RenderingCancelledException" && !cancelled) {
          console.error(`第 ${page.page + 1} 页渲染失败`, err);
          setFailed(true);
        }
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

    return () => {
      cancelled = true;
      task?.cancel?.();
    };
  }, [near, pdf, page.page, scale, w, h]);

  return (
    <div className="page-wrap" ref={hostRef} style={{ width: w, height: h }}
         data-page={page.page}>
      <canvas ref={canvasRef} style={{ width: w, height: h }} />
      {failed && <div className="page-failed">第 {page.page + 1} 页渲染失败</div>}
      {page.blocks.map((b) => {
        const skip = SKIP.has(b.type);
        return (
          <div
            key={b.id}
            data-block={b.head_id}
            className={
              "blockbox" +
              (skip ? " is-skip" : "") +
              (!skip && b.head_id === active ? " is-active" : "")
            }
            style={{
              left: b.bbox[0] * scale,
              top: b.bbox[1] * scale,
              width: (b.bbox[2] - b.bbox[0]) * scale,
              height: (b.bbox[3] - b.bbox[1]) * scale,
            }}
            onMouseEnter={() => !skip && onPick(b.head_id, "en")}
            onClick={() => !skip && onPick(b.head_id, "en", true)}
          />
        );
      })}
    </div>
  );
}

export default function PdfPane({ paneRef, docId, pages, active, onPick, onScroll }) {
  const [pdf, setPdf] = useState(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    let task = pdfjs.getDocument(`/api/documents/${docId}/file`);
    let cancelled = false;
    task.promise.then((d) => !cancelled && setPdf(d));
    return () => { cancelled = true; task.destroy?.(); };
  }, [docId]);

  // 页宽随窗口变化，留出滚动条与页边空隙
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
        <PageCanvas key={p.page} pdf={pdf} page={p} scale={scale}
                    active={active} onPick={onPick} />
      ))}
    </div>
  );
}
