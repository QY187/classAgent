"use client";
import { useEffect, useState } from "react";
import PdfDocumentPreview from "./PdfDocumentPreview";
import { errorMessage } from "../lib/api";
import { previewCourseExport, type CourseExportOptions } from "../lib/course-export";

export default function CourseExportPreview({ courseId, options, valid }: { courseId: string; options: CourseExportOptions; valid: boolean }) {
  const scopeKey = JSON.stringify(options);
  const [opened, setOpened] = useState(false), [documents, setDocuments] = useState<string[]>([]);
  const [selected, setSelected] = useState(""), [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => { setOpened(false); setDocuments([]); setSelected(""); setUrl(""); setError(""); }, [courseId, scopeKey]);
  useEffect(() => {
    if (!opened || !valid) return;
    const controller = new AbortController(); setLoading(true); setError(""); setDocuments([]); setSelected("");
    const timeout = setTimeout(() => controller.abort("timeout"), 180000);
    previewCourseExport(courseId, JSON.parse(scopeKey), controller.signal)
      .then((result) => { if (!controller.signal.aborted) { const names = result as string[]; setDocuments(names); setSelected(names[0] || ""); } })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { clearTimeout(timeout); if (!controller.signal.aborted) setLoading(false); else if (controller.signal.reason === "timeout") { setLoading(false); setError("目录加载超时，请重试或减少导出范围。"); } });
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [courseId, scopeKey, opened, valid, retry]);
  useEffect(() => {
    if (!opened || !selected || !valid) return;
    const controller = new AbortController(); let objectUrl = ""; setUrl(""); setLoading(true); setError("");
    const timeout = setTimeout(() => controller.abort("timeout"), 180000);
    previewCourseExport(courseId, JSON.parse(scopeKey), controller.signal, selected)
      .then((result) => { if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(result as Blob); setUrl(objectUrl); } })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { clearTimeout(timeout); if (!controller.signal.aborted) setLoading(false); else if (controller.signal.reason === "timeout") { setLoading(false); setError("预览等待超时，请重试或减少导出范围。"); } });
    return () => { clearTimeout(timeout); controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [courseId, scopeKey, opened, selected, valid]);
  const groups = Array.from(new Set(documents.map((name) => name.includes("/") ? name.split("/")[0] : "课程")));
  const group = selected.includes("/") ? selected.split("/")[0] : "课程";
  const inGroup = (name: string, value: string) => (name.includes("/") ? name.split("/")[0] : "课程") === value;
  return <section className="panel export-pdf-preview">
    <div className="panel-header"><h2>PDF 预览</h2><button type="button" className="button button-secondary" disabled={!valid} onClick={() => setOpened(!opened)}>{opened ? "收起预览" : "查看实际 PDF"}</button></div>
    <div className="panel-body"><p className="export-hint">与下载使用相同排版和已保存资料，不调用AI。资料后续修改会反映在重新预览和下载中。调整导出范围后请重新打开预览。</p>
    {opened && <>
      {documents.length > 0 && <div className="export-preview-controls"><label>课程 / 课次<select value={group} onChange={(event) => setSelected(documents.find((name) => inGroup(name, event.target.value)) || "")}>{groups.map((value) => <option key={value}>{value}</option>)}</select></label><label>文档<select value={selected} onChange={(event) => setSelected(event.target.value)}>{documents.filter((name) => inGroup(name, group)).map((name) => <option key={name} value={name}>{name.split("/").pop()}</option>)}</select></label></div>}
      {loading && <p role="status">正在生成真实 PDF…</p>}
      {error && <p role="alert">{error} <button className="button button-secondary" onClick={() => setRetry((value) => value + 1)}>重新加载</button></p>}
      {url && !loading && !error && <><a className="button button-secondary" href={url} target="_blank" rel="noopener noreferrer">在新窗口打开 PDF</a><p className="export-hint">可在下方翻页和缩放；也可在新窗口打开，使用浏览器阅读器搜索、选择文字或打印。缺少资料会在PDF正文说明。</p><PdfDocumentPreview key={url} title={selected} url={url} onReload={() => setRetry(value => value + 1)} /></>}
    </>}
    </div>
  </section>;
}
