"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { errorMessage, request, requestBlob } from "../../../../../lib/api";
import { type MaterialContent, processingLabels } from "../../../../../lib/materials";

function MaterialPageContent() {
  const { courseId, materialId } = useParams<{ courseId: string; materialId: string }>();
  const params = useSearchParams();
  const initial = Number(params.get("position") || 0);
  const [offset, setOffset] = useState(Number.isSafeInteger(initial) && initial >= 0 ? initial : 0);
  const version = params.get("version");
  const [data, setData] = useState<MaterialContent | null>(null);
  const [error, setError] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const base = `/courses/${courseId}/materials/${materialId}`;

  useEffect(() => {
    const controller = new AbortController();
    setError(""); setData(null);
    const query = new URLSearchParams({ offset: String(offset), limit: "10" });
    if (version) query.set("version", version);
    request<MaterialContent>(`${base}/content?${query}`, { signal: controller.signal }).then(setData)
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); });
    return () => controller.abort();
  }, [base, offset, version, refresh]);

  const filename = data?.material.filename || "";
  useEffect(() => {
    if (!filename || !/[.](pdf|pptx|docx)$/i.test(filename)) return;
    const controller = new AbortController();
    let url = "";
    setFileUrl(""); setPreviewError("");
    requestBlob(`${base}/${/[.]pdf$/i.test(filename) ? "file" : "preview.pdf"}`, { signal: controller.signal })
      .then((blob) => { if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setFileUrl(url); } })
      .catch((err) => { if (!controller.signal.aborted) setPreviewError(errorMessage(err)); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [base, filename, refresh]);

  const first = data?.items[0];
  const page = first && first.locator_type !== "paragraph" ? first.locator_number : 1;
  return <main className="content page-material-content">
    <div className="page-heading"><div><div className="eyebrow">课件来源</div><h1>{filename || "课件原文"}</h1><p>查看用于问答的提取文字，并核对原文件。图片、图表和复杂公式可能未被识别。</p></div><Link className="button button-secondary" href={`/courses/${courseId}`}>返回课程</Link></div>
    {error && <div className="notice" role="alert">{error} <button className="button button-secondary" onClick={() => setRefresh((value) => value + 1)}>重试</button></div>}
    {!data && !error && <p role="status">正在读取课件…</p>}
    {data && <>
      <p role="status">{processingLabels[data.material.processing_status]}{data.material.processing_error ? ` · ${data.material.processing_error}` : ""}</p>
      {data.source_status === "changed" && <div className="notice" role="alert">该引用对应的解析版本已变化，以下为当前版本，请重新提问核对。<button className="button button-secondary" onClick={() => setOffset(0)}>从当前版本开头查看</button></div>}
      <section className="panel"><div className="panel-header"><h2>问答原文</h2><span>按原文件位置排列</span></div><div className="panel-body">
        {data.items.length === 0 ? <p>当前没有可读取的索引文字，请返回课程查看解析状态或加入问答。</p> : data.items.map((item) => <article key={item.chunk_id} className="material-source-passage"><h3>{item.locator_label}</h3><p>{item.text}</p></article>)}
        <div className="material-source-pagination"><button className="button button-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>上一组</button><button className="button button-secondary" disabled={data.next_offset === null} onClick={() => setOffset(data.next_offset!)}>下一组</button></div>
      </div></section>
      {previewError && <p className="notice">原文件预览暂不可用：{previewError}。可返回课程下载原文件。</p>}
      {fileUrl && <section className="panel"><div className="panel-header"><h2>原文件预览</h2></div><div className="panel-body"><iframe title={filename} className="material-source-preview" src={`${fileUrl}#page=${page}`} /></div></section>}
    </>}
  </main>;
}

export default function MaterialPage() {
  return <Suspense fallback={<p role="status">正在加载课件…</p>}><MaterialPageContent /></Suspense>;
}
