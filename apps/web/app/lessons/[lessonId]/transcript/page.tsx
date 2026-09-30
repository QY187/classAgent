"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";
import { formatTime, Job, Lesson, Segment, stageLabel, TranscriptSegmentItem, saveSegment } from "../lesson-view";

export default function TranscriptPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      const nextLesson = await request<Lesson>(`/lessons/${lessonId}`);
      setLesson(nextLesson);
      try { setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`)); } catch { setSegments([]); }
      try { setJob(await request<Job>(`/lessons/${lessonId}/jobs/latest`)); } catch { setJob(null); }
    } catch (error) { setMessage(errorMessage(error)); }
  }
  useEffect(() => { if (lessonId) load(); }, [lessonId]);
  useEffect(() => { if (!job || ["completed", "failed"].includes(job.stage)) return; const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer); }, [job?.stage, lessonId]);

  async function saveText(segmentId: string, text: string) {
    const updated = await saveSegment(lessonId, segmentId, text);
    setSegments((current) => current.map((segment) => segment.id === segmentId ? updated : segment));
    setMessage("文字记录已保存，智能纪要需要重新生成。");
  }
  function download() {
    if (!segments.length) { setMessage("当前还没有可下载的文字记录。"); return; }
    const text = segments.map((segment) => `[${formatTime(segment.start_ms)}] ${segment.speaker}\n${segment.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${lesson?.title || "课堂"}-文字记录.txt`; link.click(); URL.revokeObjectURL(url);
  }

  if (!lesson) return <main className="content"><div className="empty-state"><p role="status">{message || "正在加载文字记录…"}</p>{message && <Link href="/">返回课程库</Link>}</div></main>;
  const progress = job?.progress ?? 0;
  return <main className="content transcript-page">
    <section className="page-hero page-hero-compact">
      <span className="page-hero-icon">▤</span>
      <div className="page-hero-copy">
        <div className="eyebrow">课堂资料</div>
        <h1>文字记录</h1>
        <p>{lesson.title} · 按时间和说话人阅读课堂原文</p>
      </div>
      <div className="page-hero-actions"><Link className="button button-secondary" href={`/lessons/${lesson.id}/summary`}>查看智能纪要</Link>{segments.length > 0 && <button className="button button-primary" onClick={download}>下载文字</button>}</div>
    </section>
    <div className="document-toolbar"><div className="lesson-view-tabs"><Link className="active" href={`/lessons/${lesson.id}/transcript`}>文字记录</Link><Link href={`/lessons/${lesson.id}/summary`}>智能纪要</Link></div>{job && <span className={`pill pill-${job.stage}`}>{stageLabel[job.stage] || job.stage}</span>}</div>
    {message && <div className="notice" style={{ marginBottom: 18 }}>{message}</div>}
    <section className="panel document-panel"><div className="panel-header"><div><h2>{lesson.title}</h2><span className="summary-caption">原始录音的文字记录 · 时间戳和说话人均保留</span></div><span>{segments.length} 段</span></div><div className="panel-body">{job && job.stage !== "completed" && <div style={{ marginBottom: 18 }}><div className="progress-label"><span>{stageLabel[job.stage] || job.stage}</span><span>{progress}%</span></div><div className="job-progress"><span style={{ width: `${progress}%` }} /></div>{job.error_message && <div className="notice" style={{ marginTop: 10 }}>{job.error_message}</div>}</div>}{segments.length ? <div className="transcript">{segments.map((segment) => <TranscriptSegmentItem key={segment.id} segment={segment} onSave={saveText} />)}</div> : <div className="empty-state"><div className="empty-icon">◌</div><strong>{job?.stage === "completed" ? "暂无文字记录" : "文字记录还在准备中"}</strong><p>完成浏览器录音或音频转写后，课堂原文会显示在这里。</p><Link className="button button-secondary" href={`/lessons/${lesson.id}`}>返回课次工作台</Link></div>}</div></section>
  </main>;
}
