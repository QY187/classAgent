"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";
import { Lesson, Segment, Summary, parseSummaryContent } from "../lesson-view";
import FeishuEditor from "../../../../components/FeishuEditor";
import Html from "../../../../components/Html";
import { summaryToHtml } from "../../../../lib/summary-html";

function toDocHtml(status: string | undefined, content: string | null | undefined): string {
  if (status === "edited" && content) return content;
  const parsed = parseSummaryContent(content);
  return parsed ? summaryToHtml(parsed) : "";
}

export default function SummaryPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      setLesson(await request<Lesson>(`/lessons/${lessonId}`));
      try { setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`)); } catch { setSegments([]); }
      try { setSummary(await request<Summary>(`/lessons/${lessonId}/summary`)); } catch { setSummary(null); }
    } catch (error) { setMessage(errorMessage(error)); }
  }
  useEffect(() => { if (lessonId) load(); }, [lessonId]);
  useEffect(() => { if (!summary || ["completed", "failed", "stale", "edited"].includes(summary.status)) return; const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer); }, [summary?.status, lessonId]);

  async function generate() {
    if (!segments.length || loading || summary?.status === "generating" || summary?.status === "queued") return;
    setLoading(true); setMessage("正在生成智能纪要，请稍候…");
    try { setSummary(await request<Summary>(`/lessons/${lessonId}/summary`, { method: "POST" })); } catch (error) { setMessage(errorMessage(error)); } finally { setLoading(false); }
  }

  function startEdit() {
    setDraft(toDocHtml(summary?.status, summary?.content));
    setEditing(true);
  }

  async function saveEdit() {
    if (!draft.trim() || saving) return;
    setSaving(true); setMessage("");
    try {
      setSummary(await request<Summary>(`/lessons/${lessonId}/summary`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: draft }) }));
      setEditing(false);
      setMessage("纪要已保存你的修改。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setSaving(false); }
  }

  if (!lesson) return <main className="content"><div className="empty-state"><p role="status">{message || "正在加载智能纪要…"}</p>{message && <Link href="/">返回课程库</Link>}</div></main>;
  const isEdited = summary?.status === "edited";
  const docHtml = toDocHtml(summary?.status, summary?.content);
  const statusLabel = summary?.status === "completed" ? "已完成" : summary?.status === "edited" ? "已手动编辑" : summary?.status === "generating" ? "生成中" : summary?.status === "failed" ? "生成失败" : summary?.status === "stale" ? "需要更新" : "等待生成";
  const canEdit = Boolean(summary && (summary.status === "completed" || summary.status === "edited" || summary.status === "stale"));
  return <main className="content summary-page">
    <section className="page-hero page-hero-compact">
      <span className="page-hero-icon">✦</span>
      <div className="page-hero-copy">
        <div className="eyebrow">课堂资料</div>
        <h1>智能纪要</h1>
        <p>{lesson.title} · 提炼课程重点，帮助课后复习</p>
      </div>
      <div className="page-hero-actions">
        <Link className="button button-secondary" href={`/lessons/${lesson.id}/transcript`}>查看文字记录</Link>
        {canEdit && !editing && <button className="button button-secondary" onClick={startEdit}>编辑纪要</button>}
        <button className="button button-primary" onClick={generate} disabled={!segments.length || loading || summary?.status === "generating" || summary?.status === "queued"}>{loading || summary?.status === "generating" || summary?.status === "queued" ? "生成中…" : summary ? "重新生成" : "生成智能纪要"}</button>
      </div>
    </section>
    <div className="document-toolbar"><div className="lesson-view-tabs"><Link href={`/lessons/${lesson.id}/transcript`}>文字记录</Link><Link className="active" href={`/lessons/${lesson.id}/summary`}>智能纪要</Link></div><span className={`pill pill-${summary?.status || "created"}`}>{statusLabel}</span></div>
    {message && <div className="notice" style={{ marginBottom: 18 }}>{message}</div>}
    <section className="panel document-panel"><div className="panel-header"><div><h2>课堂重点</h2><span className="summary-caption">由课堂文字记录整理，可随时重新生成</span></div><span>{docHtml ? "文档" : "等待内容"}</span></div><div className="panel-body">{editing ? <div className="summary-editor-wrap"><FeishuEditor value={draft} onChange={setDraft} /><div className="summary-editor-actions"><button className="button button-secondary" onClick={() => setEditing(false)} disabled={saving}>取消</button><button className="button button-primary" onClick={saveEdit} disabled={saving || !draft.trim()}>{saving ? "保存中…" : "保存修改"}</button></div></div> : docHtml ? <><Html source={docHtml} />{isEdited && <div className="summary-edited-note">你已手动编辑此纪要。重新生成将覆盖这些修改。</div>}</> : summary?.status === "stale" ? <div className="summary-placeholder"><div className="empty-icon">↻</div><strong>文字记录有更新</strong><p>重新生成智能纪要，才能同步最新课堂内容。</p><button className="button button-primary" onClick={generate} disabled={!segments.length || loading}>重新生成</button></div> : summary?.status === "failed" ? <div className="summary-placeholder"><div className="empty-icon">!</div><strong>纪要生成失败</strong><p>{summary.error_message || "请稍后重试。"}</p><button className="button button-primary" onClick={generate} disabled={!segments.length || loading}>再次生成</button></div> : summary?.status === "queued" || summary?.status === "generating" ? <div className="summary-placeholder"><div className="empty-icon">✦</div><strong>正在整理这节课的重点</strong><p>纪要生成完成后会自动出现在这里。</p></div> : <div className="summary-placeholder"><div className="empty-icon">✦</div><strong>{segments.length ? "生成一份可复习的课堂纪要" : "先完成文字记录"}</strong><p>{segments.length ? "提取课程主题、关键概念、例题、作业和待核对内容。" : "浏览器录音识别或上传音频转写完成后，即可生成纪要。"}</p>{segments.length && <button className="button button-primary" onClick={generate}>生成智能纪要</button>}</div>}</div></section>
  </main>;
}
