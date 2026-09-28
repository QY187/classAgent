"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";

type Lesson = { id: string; course_id: string; title: string; lesson_date?: string | null; status: string };
type Job = { id: string; lesson_id: string; stage: string; progress: number; error_message?: string | null };
type Segment = { id: string; speaker: string; start_ms: number; end_ms: number; text: string; source: string };
const stageLabel: Record<string, string> = { queued: "等待处理", transcribing: "正在转写", completed: "处理完成", failed: "处理失败" };

function formatTime(ms: number) { const seconds = Math.floor(ms / 1000); return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`; }

export default function LessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    try {
    setLesson(await request<Lesson>(`/lessons/${lessonId}`));
    try { setJob(await request<Job>(`/lessons/${lessonId}/jobs/latest`)); } catch { setJob(null); }
    try { setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`)); } catch { setSegments([]); }
    } catch (error) { setMessage(errorMessage(error)); }
  }
  useEffect(() => { if (lessonId) load(); }, [lessonId]);
  useEffect(() => { if (!job || ["completed", "failed"].includes(job.stage)) return; const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer); }, [job?.stage, lessonId]);

  async function uploadAudio(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (uploading) return;
    setUploading(true); setMessage("音频上传中，请稍候…");
    try {
    const body = new FormData(); body.append("file", file);
    setJob(await request<Job>(`/lessons/${lessonId}/audio`, { method: "POST", body }));
    setSegments([]); setMessage("上传成功，已加入处理队列。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setUploading(false); event.target.value = ""; }
  }

  if (!lesson) return <main className="content"><div className="empty-state"><p role="status">{message || "正在加载课次…"}</p>{message && <><Link href="/">返回课程库</Link><button className="button button-secondary" onClick={load}>重试</button></>}</div></main>;
  const progress = job?.progress ?? 0;
  return <main className="content"><Link className="back-link" href={`/courses/${lesson.course_id}`}>← 返回课程</Link><div className="page-heading"><div><div className="eyebrow">课次详情</div><h1>{lesson.title}</h1><p>{lesson.lesson_date || "未设置日期"} · 课堂资料</p></div><label className="button button-primary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading} />{uploading ? "上传中…" : "上传课堂音频"}</label></div>{message && <div className="notice" style={{ marginBottom: 18 }}>{message}</div>}<div className="detail-grid"><section className="panel"><div className="panel-header"><h2>文字记录</h2>{job && <span className={`pill pill-${job.stage}`}>{stageLabel[job.stage] || job.stage}</span>}</div><div className="panel-body">{job && job.stage !== "completed" && <div style={{ marginBottom: 18 }}><div style={{ display: "flex", justifyContent: "space-between", color: "#6b7280", fontSize: 12 }}><span>{stageLabel[job.stage] || job.stage}</span><span>{progress}%</span></div><div className="job-progress"><span style={{ width: `${progress}%` }} /></div>{job.error_message && <div className="notice" style={{ marginTop: 10 }}>{job.error_message}</div>}</div>}{segments.length ? <div className="transcript">{segments.map((segment) => <div className="transcript-segment" key={segment.id}><div><div className="speaker">{segment.speaker}</div><div className="timecode">{formatTime(segment.start_ms)}</div></div><div className="transcript-text">{segment.text}</div></div>)}</div> : <div className="empty-state"><div className="empty-icon">◌</div><strong>{job?.stage === "completed" ? "暂时没有转写片段" : "上传音频后生成文字记录"}</strong><p>完成处理后，课堂内容会按说话人和时间点显示在这里。</p></div>}</div></section><aside className="panel"><div className="panel-header"><h2>音频与处理</h2></div><div className="panel-body"><div className="upload-box"><div style={{ fontSize: 28 }}>♫</div><strong>上传这节课的录音</strong><p>支持常见音频格式，系统会在后台完成处理。</p><label className="button button-secondary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading} />选择音频文件</label></div><div className="notice" style={{ marginTop: 16 }}>当前技术验证版使用 mock 转写。下一步接入真实 ASR 后，这里会展示真实课堂文字。</div></div></aside></div></main>;
}
