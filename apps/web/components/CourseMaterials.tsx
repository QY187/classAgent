"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { errorMessage, request, requestBlob } from "../lib/api";
import { type Material, materialHref, processingLabels } from "../lib/materials";
import ResponsiveActions from "./ResponsiveActions";

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
  const [indexBusy, setIndexBusy] = useState<string | null>(null);
  const [replacing, setReplacing] = useState<Material | null>(null);
  const [replacementFile, setReplacementFile] = useState<File | null>(null);
  const [replaceBusy, setReplaceBusy] = useState(false);
  const [replaceError, setReplaceError] = useState("");
  const materialRevision = useRef(0);
  const previewRequest = useRef(0);
  const previewUrl = useRef<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const lessonMaterials = materials.filter((material) => material.lesson_id === (lessonId || null));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    request<Material[]>(`/courses/${courseId}/materials`, { signal: controller.signal }).then((items) => { if (!controller.signal.aborted) setMaterials(items); }).catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [courseId, refreshKey]);

  const processing = materials.some((item) => ["queued", "processing", "indexing"].includes(item.processing_status));
  useEffect(() => {
    if (!processing) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      const revision = materialRevision.current;
      request<Material[]>(`/courses/${courseId}/materials`, { signal: controller.signal })
        .then((items) => { if (!controller.signal.aborted && revision === materialRevision.current) { setMaterials(items); setError(""); } }).catch((err) => { if (!controller.signal.aborted && revision === materialRevision.current) setError(errorMessage(err)); });
    }, 2500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [courseId, processing]);

  async function buildIndex(material: Material) {
    materialRevision.current += 1;
    setIndexBusy(material.id); setError("");
    try {
      const updated = await request<Material>(`/courses/${courseId}/materials/${material.id}/index`, { method: "POST" });
      setMaterials((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (err) { setError(errorMessage(err)); }
    finally { setIndexBusy(null); }
  }

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
  useEffect(() => {
    if (!replacing || replaceBusy) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setReplacing(null); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [Boolean(replacing), replaceBusy]);

  function askReplace(material: Material) {
    setReplacementFile(null); setReplaceError(""); setReplacing(material);
  }

  async function confirmReplace() {
    if (!replacing || !replacementFile || replaceBusy) return;
    if (!/[.](pdf|pptx|docx|txt|md)$/i.test(replacementFile.name)) { setReplaceError("请选择文字型 PDF、PPTX、DOCX、TXT 或 Markdown。"); return; }
    if (replacementFile.size === 0 || replacementFile.size > 25 * 1024 * 1024) { setReplaceError("资料大小须在 1 字节至 25 MB 之间。"); return; }
    materialRevision.current += 1;
    setReplaceBusy(true); setReplaceError("");
    try {
      const body = new FormData(); body.append("file", replacementFile);
      const updated = await request<Material>(`/courses/${courseId}/materials/${replacing.id}/file`, { method: "PUT", body, signal: AbortSignal.timeout(120000) });
      setMaterials((items) => items.map((item) => item.id === updated.id ? updated : item));
      setReplacing(null); setReplacementFile(null);
    } catch (err) { setReplaceError(errorMessage(err)); }
    finally { setReplaceBusy(false); }
  }

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
    materialRevision.current += 1;
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
    <div className="lesson-materials-heading"><strong>{lessonId ? "本节资料" : "课程公共资料"}</strong><span>{lessonMaterials.length} 份</span></div>
      {error && <p className="notice" role="alert">{error}</p>}
      {downloadError && <p className="notice" role="alert">下载失败：{downloadError}</p>}
      {loading ? <p role="status" className="material-muted">正在加载资料…</p> : lessonMaterials.length === 0 ? <div className="material-empty">还没有资料，点击上方“上传资料”即可添加。</div> : <div className="material-list">{lessonMaterials.map((material) => <div className="material-row" key={material.id}>
        <span className="material-icon" aria-hidden="true">▤</span>
        <div className="material-info"><button type="button" className="material-name" title={material.filename} onClick={() => openPreview(material)}>{material.filename}</button><span>{sizeLabel(material.size_bytes)} · {new Date(material.created_at).toLocaleDateString("zh-CN")} · {processingLabels[material.processing_status] || "已保存"}{material.indexed && material.processing_status !== "ready" ? " · 上一版本仍可问答" : ""}</span>{material.replacement_filename && <span role="status">待替换：{material.replacement_filename} · 成功后切换原文件与索引</span>}{material.processing_error && <span role="status">{material.processing_error}</span>}</div>
        <div className="material-actions">
          {material.indexed && <Link className="button button-secondary" href={materialHref({ course_id: courseId, material_id: material.id })}>问答原文</Link>}
          {["stored", "failed"].includes(material.processing_status || "stored") && <button type="button" className="button button-secondary" disabled={indexBusy !== null} onClick={() => buildIndex(material)}>{indexBusy === material.id ? "正在提交…" : material.processing_status === "failed" ? "重试解析" : "加入问答"}</button>}
          <button type="button" className="button button-secondary" onClick={() => openPreview(material)}>查看</button>
          <button type="button" className="button button-secondary" onClick={() => download(material)}>下载</button>
          <ResponsiveActions label={`${material.filename}的更多操作`}>
            <button type="button" className="button button-secondary" onClick={() => askReplace(material)}>替换文件</button>
            <button type="button" className="button material-delete-button" onClick={() => askDelete(material)}>删除</button>
          </ResponsiveActions>
        </div>
      </div>)}</div>}
    {deleting && createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (!deleteBusy && event.target === event.currentTarget) setDeleting(null); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="material-delete-title">
      <h2 id="material-delete-title">删除资料</h2>
      <p>确定删除「<strong className="material-delete-filename">{deleting.filename}</strong>」吗？资料将移入回收站，30 天内可恢复，到期自动彻底删除。</p>
      {deleteError && <p className="notice" role="alert">删除失败：{deleteError}</p>}
      <div className="modal-actions"><button type="button" className="button button-secondary" autoFocus disabled={deleteBusy} onClick={() => setDeleting(null)}>取消</button><button type="button" className="button button-danger" disabled={deleteBusy} onClick={confirmDelete}>{deleteBusy ? "正在移入…" : "移入回收站"}</button></div>
    </div></div>, document.body)}
    {replacing && createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (!replaceBusy && event.target === event.currentTarget) setReplacing(null); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="material-replace-title">
      <h2 id="material-replace-title">替换文件</h2>
      <p>替换「<strong className="material-delete-filename">{replacing.filename}</strong>」。新文件解析成功后，原文件、切片和向量会一起更新；失败时保留当前版本。已有回答的旧引用将提示版本变化。</p>
      {replacing.replacement_filename && <p>当前待替换文件：{replacing.replacement_filename}。再次提交将以本次选择为准。</p>}
      <label className="material-replacement-input">选择新文件<input autoFocus type="file" accept=".pdf,.pptx,.docx,.txt,.md" disabled={replaceBusy} onChange={(event) => { setReplacementFile(event.target.files?.[0] || null); setReplaceError(""); }} /></label>
      <p className="material-muted">最多 25 MB，支持文字型 PDF、PPTX、DOCX、TXT、Markdown；扫描件暂不支持 OCR。</p>
      {replaceError && <p className="notice" role="alert">{replaceError}</p>}
      <div className="modal-actions"><button type="button" className="button button-secondary" disabled={replaceBusy} onClick={() => setReplacing(null)}>取消</button><button type="button" className="button" disabled={replaceBusy || !replacementFile} onClick={confirmReplace}>{replaceBusy ? "正在上传…" : "上传并替换"}</button></div>
    </div></div>, document.body)}
    {preview && createPortal(<div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePreview(); }}><div className="modal material-preview-modal" role="dialog" aria-modal="true" aria-label={`查看${preview.filename}`}>
      <div className="material-preview-header"><h2 title={preview.filename}>{preview.filename}</h2><button ref={closeButton} type="button" className="button button-secondary" onClick={closePreview}>关闭</button></div>
      {/[.](doc|docx|ppt|pptx)$/i.test(preview.filename) && <p className="material-preview-hint">已转换为 PDF 预览；字体或排版可能与原文件略有差异，原文件可在列表中下载。</p>}
      {preview.loading ? <p role="status">正在加载预览…</p> : preview.error ? <p className="notice" role="alert">{preview.error}</p> : preview.kind === "pdf" && preview.url ? <iframe className="material-preview-frame" title={preview.filename} src={preview.url} /> : preview.kind === "image" && preview.url ? <img className="material-preview-image" src={preview.url} alt={preview.filename} /> : <div className="material-preview-text">{preview.text || "文档中没有可提取的文字。"}{preview.truncated && <p className="material-preview-truncated">预览仅显示前 10 万字，请下载查看完整内容。</p>}</div>}
    </div></div>, document.body)}
  </div>;
}

