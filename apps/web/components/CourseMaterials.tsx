"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { errorMessage, request, requestBlob } from "../lib/api";

type Material = { id: string; lesson_id: string | null; filename: string; size_bytes: number; created_at: string; status: string };
type Preview = { filename: string; kind: "pdf" | "image" | "text"; loading: boolean; url?: string; text?: string; truncated?: boolean; error?: string };

function sizeLabel(bytes: number) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function CourseMaterials({ courseId, lessonId, refreshKey }: { courseId: string; lessonId: string; refreshKey: number }) {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const [deleting, setDeleting] = useState<Material | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const previewRequest = useRef(0);
  const previewUrl = useRef<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const lessonMaterials = materials.filter((material) => material.lesson_id === lessonId);

  useEffect(() => {
    setLoading(true);
    request<Material[]>(`/courses/${courseId}/materials`).then(setMaterials).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false));
  }, [courseId, refreshKey]);

  useEffect(() => () => { previewRequest.current += 1; if (previewUrl.current) URL.revokeObjectURL(previewUrl.current); }, []);
  useEffect(() => {
    if (!preview) return;
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") closePreview(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [Boolean(preview)]);
  useEffect(() => {
    if (!deleting || deleteBusy) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setDeleting(null); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [Boolean(deleting), deleteBusy]);

  function closePreview() {
    previewRequest.current += 1;
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = null;
    setPreview(null);
  }

  async function openPreview(material: Material) {
    closePreview();
    const requestId = previewRequest.current;
    const suffix = material.filename.split(".").pop()?.toLowerCase();
    const office = ["doc", "docx", "ppt", "pptx"].includes(suffix || "");
    const kind = suffix === "pdf" || office ? "pdf" : ["png", "jpg", "jpeg", "webp"].includes(suffix || "") ? "image" : "text";
    setPreview({ filename: material.filename, kind, loading: true });
    try {
      if (["txt", "md"].includes(suffix || "")) {
        const result = await request<{ text: string; truncated: boolean }>(`/courses/${courseId}/materials/${material.id}/preview`, { signal: AbortSignal.timeout(120000) });
        if (requestId === previewRequest.current) setPreview({ filename: material.filename, kind: "text", loading: false, ...result });
      } else if (kind === "pdf" || kind === "image") {
        const path = office ? `/courses/${courseId}/materials/${material.id}/preview.pdf` : `/courses/${courseId}/materials/${material.id}/file`;
        const blob = await requestBlob(path, { signal: AbortSignal.timeout(120000) });
        if (requestId !== previewRequest.current) return;
        const url = URL.createObjectURL(blob);
        previewUrl.current = url;
        setPreview({ filename: material.filename, kind, loading: false, url });
      } else {
        setPreview({ filename: material.filename, kind: "text", loading: false, error: "该格式暂不支持在线预览，请下载原文件查看。" });
      }
    } catch (error) {
      if (requestId === previewRequest.current) setPreview({ filename: material.filename, kind, loading: false, error: errorMessage(error) });
    }
  }

  async function download(material: Material) {
    setDownloadError("");
    try {
      const blob = await requestBlob(`/courses/${courseId}/materials/${material.id}/file?download=true`, { signal: AbortSignal.timeout(120000) });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = material.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) { setDownloadError(errorMessage(error)); }
  }

  function askDelete(material: Material) {
    setDeleteError("");
    setDeleting(material);
  }

  async function confirmDelete() {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await request<void>(`/courses/${courseId}/materials/${deleting.id}`, { method: "DELETE" });
      setMaterials((current) => current.filter((material) => material.id !== deleting.id));
      setDeleting(null);
    } catch (error) {
      setDeleteError(errorMessage(error));
    } finally {
      setDeleteBusy(false);
    }
  }

  return <div className="lesson-materials" id={`lesson-materials-${lessonId}`}>
    <div className="lesson-materials-heading"><strong>本节资料</strong><span>{lessonMaterials.length} 份</span></div>
      {error && <p className="notice" role="alert">{error}</p>}
      {downloadError && <p className="notice" role="alert">下载失败：{downloadError}</p>}
      {loading ? <p role="status" className="material-muted">正在加载资料…</p> : lessonMaterials.length === 0 ? <div className="material-empty">这节课还没有资料，点击上方“上传资料”即可添加。</div> : <div className="material-list">{lessonMaterials.map((material) => <div className="material-row" key={material.id}>
        <span className="material-icon" aria-hidden="true">▤</span>
        <div className="material-info"><button type="button" className="material-name" title={material.filename} onClick={() => openPreview(material)}>{material.filename}</button><span>{sizeLabel(material.size_bytes)} · {new Date(material.created_at).toLocaleDateString("zh-CN")} · {material.status === "stored" ? "已保存" : material.status}</span></div>
        <div className="material-actions"><button type="button" className="button button-secondary" onClick={() => openPreview(material)}>查看</button><button type="button" className="button button-secondary" onClick={() => download(material)}>下载</button><button type="button" className="button material-delete-button" onClick={() => askDelete(material)}>删除</button></div>
      </div>)}</div>}
    {deleting && createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (!deleteBusy && event.target === event.currentTarget) setDeleting(null); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="material-delete-title">
      <h2 id="material-delete-title">删除资料</h2>
      <p>确定删除「<strong className="material-delete-filename">{deleting.filename}</strong>」吗？资料将移入回收站，之后可以恢复。</p>
      {deleteError && <p className="notice" role="alert">删除失败：{deleteError}</p>}
      <div className="modal-actions"><button type="button" className="button button-secondary" autoFocus disabled={deleteBusy} onClick={() => setDeleting(null)}>取消</button><button type="button" className="button button-danger" disabled={deleteBusy} onClick={confirmDelete}>{deleteBusy ? "正在移入…" : "移入回收站"}</button></div>
    </div></div>, document.body)}
    {preview && createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePreview(); }}><div className="modal material-preview-modal" role="dialog" aria-modal="true" aria-label={`查看${preview.filename}`}>
      <div className="material-preview-header"><h2 title={preview.filename}>{preview.filename}</h2><button ref={closeButton} type="button" className="button button-secondary" onClick={closePreview}>关闭</button></div>
      {/[.](doc|docx|ppt|pptx)$/i.test(preview.filename) && <p className="material-preview-hint">已转换为 PDF 预览；字体或排版可能与原文件略有差异，原文件可在列表中下载。</p>}
      {preview.loading ? <p role="status">正在加载预览…</p> : preview.error ? <p className="notice" role="alert">{preview.error}</p> : preview.kind === "pdf" && preview.url ? <iframe className="material-preview-frame" title={preview.filename} src={preview.url} /> : preview.kind === "image" && preview.url ? <img className="material-preview-image" src={preview.url} alt={preview.filename} /> : <div className="material-preview-text">{preview.text || "文档中没有可提取的文字。"}{preview.truncated && <p className="material-preview-truncated">预览仅显示前 10 万字，请下载查看完整内容。</p>}</div>}
    </div></div>, document.body)}
  </div>;
}
