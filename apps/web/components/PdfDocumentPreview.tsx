"use client";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";

export default function PdfDocumentPreview({ url, title, onReload }: { url: string; title: string; onReload: () => void }) {
  const host = useRef<HTMLDivElement>(null), viewport = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1), [zoom, setZoom] = useState(1), [width, setWidth] = useState(0);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [drawRetry, setDrawRetry] = useState(0);

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    let frame = 0, previousOuterWidth = -1;
    const resize = () => {
      // ResizeObserver也会在高度/滚动条变化时通知，只响应阅读区外部宽度变化。
      const outerWidth = element.getBoundingClientRect().width;
      if (Math.abs(outerWidth - previousOuterWidth) < 1) return;
      previousOuterWidth = outerWidth;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setWidth(element.clientWidth));
    };
    resize();
    const observer = new ResizeObserver(resize); observer.observe(element, { box: "border-box" });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);

  useEffect(() => {
    let disposed = false, task: PDFDocumentLoadingTask | undefined;
    setPdf(null); setPage(1); setZoom(1); setLoading(true); setError(""); host.current?.replaceChildren();
    async function load() {
      try {
        const engine = await import("pdfjs-dist");
        if (disposed) return;
        engine.GlobalWorkerOptions.workerSrc = `/vendor/pdfjs/pdf.worker-${engine.version}.min.mjs`;
        task = engine.getDocument({ url });
        const document = await task.promise;
        if (!disposed) setPdf(document);
      } catch {
        if (!disposed) { setLoading(false); setError("PDF阅读器加载失败，请重新加载，或在新窗口打开。 "); }
      }
    }
    void load();
    return () => { disposed = true; void task?.destroy().catch(() => {}); };
  }, [url]);

  useEffect(() => {
    if (!pdf || !width) return;
    let disposed = false, render: RenderTask | undefined;
    setLoading(true); setError("");
    // 新页在离屏Canvas画好后原子替换，避免清空内容引起高度和滚动条反复变化。
    if (viewport.current) { viewport.current.scrollTop = 0; viewport.current.scrollLeft = 0; }
    async function draw() {
      try {
        const documentPage = await pdf!.getPage(page);
        if (disposed) return;
        const natural = documentPage.getViewport({ scale: 1 });
        const fitted = documentPage.getViewport({ scale: Math.max(1, width - 32) / natural.width * zoom });
        // 只绘制当前页；限制像素预算，避免高分屏及放大时分配过大的Canvas。
        const ratio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8_000_000 / (fitted.width * fitted.height)));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.ceil(fitted.width * ratio));
        canvas.height = Math.max(1, Math.ceil(fitted.height * ratio));
        canvas.style.width = `${fitted.width}px`; canvas.style.height = `${fitted.height}px`;
        canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", `${title}，第${page}页，共${pdf!.numPages}页`);
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas unavailable");
        render = documentPage.render({ canvas, canvasContext: context, viewport: fitted, transform: [ratio, 0, 0, ratio, 0, 0] });
        await render.promise;
        if (disposed) return;
        const text = await documentPage.getTextContent();
        if (disposed) return;
        canvas.textContent = text.items.map(item => "str" in item ? item.str : "").join(" ");
        canvas.dataset.page = String(page); canvas.dataset.rendered = "true"; canvas.dataset.zoom = String(zoom);
        host.current?.replaceChildren(canvas); setLoading(false);
      } catch {
        if (!disposed) { setLoading(false); setError("这一页暂时无法显示，请重新绘制，或在新窗口打开。 "); }
      }
    }
    void draw();
    return () => { disposed = true; render?.cancel(); };
  }, [pdf, page, width, zoom, drawRetry, title]);

  return <div className="pdf-document-reader">
    <div className="pdf-reader-toolbar" role="group" aria-label="PDF阅读控制">
      <button type="button" className="button button-secondary" disabled={!pdf || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button>
      <span className="pdf-reader-page" aria-live="polite">第 {page} / {pdf?.numPages ?? "…"} 页</span>
      <button type="button" className="button button-secondary" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage(value => value + 1)}>下一页</button>
      <label>缩放<select aria-label="PDF预览缩放" value={zoom} disabled={!pdf} onChange={event => setZoom(Number(event.target.value))}>
        <option value={1}>适合宽度</option><option value={0.75}>75%</option><option value={1.25}>125%</option><option value={1.5}>150%</option><option value={2}>200%</option>
      </select></label>
    </div>
    {loading && <p role="status">正在绘制第 {page} 页…</p>}
    {error && <p role="alert">{error}<button type="button" className="button button-secondary" onClick={() => pdf ? setDrawRetry(value => value + 1) : onReload()}>重试显示</button></p>}
    <div className="pdf-reader-viewport" ref={viewport} aria-busy={loading}>
      <div className="pdf-reader-page-host" ref={host} />
    </div>
  </div>;
}
