"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, apiUrl, request } from "../../../../lib/api";
import { getToken } from "../../../../lib/auth";
import { formatTime, Job, Lesson, Segment, stageLabel, TranscriptSegmentItem, saveSegment } from "../lesson-view";
import AudioPlayer from "../../../../components/AudioPlayer";

export default function TranscriptPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [speakers, setSpeakers] = useState<{ raw_label: string; display_name: string }[]>([]);
  const [speakerOpen, setSpeakerOpen] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [merging, setMerging] = useState(false);
  const [message, setMessage] = useState("");
  const [audioMeta, setAudioMeta] = useState<{ id: string; filename: string; content_type: string; size_bytes: number } | null>(null);
  const [seek, setSeek] = useState<{ ms: number; n: number } | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const scrolledTimeRef = useRef<string | null>(null);

  const aliasMap = Object.fromEntries(speakers.map((item) => [item.raw_label, item.display_name]));
  const displayName = (raw: string) => aliasMap[raw] || raw;
  function seekTo(ms: number) { setSeek((prev) => ({ ms, n: (prev ? prev.n : 0) + 1 })); }

  async function load() {
    try {
      const nextLesson = await request<Lesson>(`/lessons/${lessonId}`);
      setLesson(nextLesson);
      try {
        const transcript = await request<Segment[]>(`/lessons/${lessonId}/transcript`);
        setSegments(transcript);
        const target = Number(new URLSearchParams(window.location.search).get("t"));
        if (window.location.search.includes("t=") && Number.isFinite(target) && target >= 0) seekTo(target);
      } catch { setSegments([]); }
      try { setJob(await request<Job>(`/lessons/${lessonId}/jobs/latest`)); } catch { setJob(null); }
      try { setSpeakers(await request<{ raw_label: string; display_name: string }[]>(`/lessons/${lessonId}/speakers`)); } catch { setSpeakers([]); }
      try { setAudioMeta(await request<{ id: string; filename: string; content_type: string; size_bytes: number }>(`/lessons/${lessonId}/audio/meta`)); } catch { setAudioMeta(null); }
    } catch (error) { setMessage(errorMessage(error)); }
  }
  useEffect(() => { if (lessonId) load(); }, [lessonId]);
  useEffect(() => { if (!job || ["completed", "failed"].includes(job.stage)) return; const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer); }, [job?.stage, lessonId]);
  useEffect(() => {
    if (!segments.length) return;
    const value = new URLSearchParams(window.location.search).get("t");
    if (value === null || scrolledTimeRef.current === value) return;
    const target = Number(value);
    if (!Number.isFinite(target) || target < 0) return;
    const nextIndex = segments.findIndex((segment) => segment.start_ms > target);
    const index = nextIndex < 0 ? segments.length - 1 : Math.max(0, nextIndex - 1);
    setActiveId(segments[index].id);
    scrolledTimeRef.current = value;
    requestAnimationFrame(() => document.querySelectorAll(".transcript-segment")[index]?.scrollIntoView({ block: "center" }));
  }, [segments]);

  async function saveText(segmentId: string, text: string) {
    const updated = await saveSegment(lessonId, segmentId, text);
    setSegments((current) => current.map((segment) => segment.id === segmentId ? updated : segment));
    setMessage("文字记录已保存，智能纪要需要重新生成。");
  }
  function download() {
    if (!segments.length) { setMessage("当前还没有可下载的文字记录。"); return; }
    const text = segments.map((segment) => `[${formatTime(segment.start_ms)}] ${displayName(segment.speaker)}\n${segment.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${lesson?.title || "课堂"}-文字记录.txt`; link.click(); URL.revokeObjectURL(url);
  }
  function toggleSpeakerManager() {
    if (!speakerOpen) setDrafts(Object.fromEntries(speakers.map((item) => [item.raw_label, item.display_name])));
    setSpeakerOpen((value) => !value);
  }
  async function saveSpeakers() {
    try {
      const next = await request<{ raw_label: string; display_name: string }[]>(`/lessons/${lessonId}/speakers`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(drafts),
      });
      setSpeakers(next);
      setMessage("说话人名称已保存。");
      setSpeakerOpen(false);
    } catch (error) { setMessage(errorMessage(error)); }
  }
  async function mergeNext(segment: Segment) {
    const index = segments.findIndex((item) => item.id === segment.id);
    const nextSegment = segments[index + 1];
    if (!nextSegment || merging) return;
    setMerging(true);
    try {
      await request(`/lessons/${lessonId}/transcript/merge`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ first_id: segment.id, second_id: nextSegment.id }),
      });
      setMessage("已合并相邻片段。");
      await load();
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setMerging(false); }
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
    <section className="panel document-panel"><div className="panel-header"><div><h2>{lesson.title}</h2><span className="summary-caption">原始录音的文字记录 · 时间戳和说话人均保留</span></div><div className="speaker-bar">{segments.length > 0 && <button className="button button-secondary" type="button" onClick={toggleSpeakerManager}>说话人管理（{speakers.length}）</button>}<span>{segments.length} 段</span>{speakerOpen && <div className="speaker-panel">
        <div className="speaker-panel-head"><strong>重命名说话人</strong><button className="button button-quiet" type="button" onClick={() => setSpeakerOpen(false)}>收起</button></div>
        {speakers.length === 0 ? <p className="speaker-empty">本课次还没有可命名的说话人。</p> : <div className="speaker-list">{speakers.map((item) => <label key={item.raw_label} className="speaker-field"><span className="speaker-field-from">{item.raw_label}</span><span className="speaker-arrow" aria-hidden="true">→</span><input className="field" value={drafts[item.raw_label] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [item.raw_label]: event.target.value }))} placeholder="如：老师 / 同学" /></label>)}</div>}
        <div className="speaker-panel-actions"><button className="button button-primary" type="button" onClick={saveSpeakers}>保存名称</button></div>
      </div>}</div></div><div className="panel-body">{audioMeta && segments.length > 0 && <AudioPlayer src={`${apiUrl}/lessons/${lessonId}/audio?token=${encodeURIComponent(getToken() ?? "")}`} segments={segments.map((segment) => ({ id: segment.id, start_ms: segment.start_ms }))} seek={seek} onActiveChange={setActiveId} />}{job && job.stage !== "completed" && <div style={{ marginBottom: 18 }}><div className="progress-label"><span>{stageLabel[job.stage] || job.stage}</span><span>{progress}%</span></div><div className="job-progress"><span style={{ width: `${progress}%` }} /></div>{job.error_message && <div className="notice" style={{ marginTop: 10 }}>{job.error_message}</div>}</div>}{segments.length ? <div className="transcript">{segments.map((segment, index) => <TranscriptSegmentItem key={segment.id} segment={segment} onSave={saveText} displayName={displayName(segment.speaker)} onMerge={index < segments.length - 1 ? () => mergeNext(segment) : undefined} onSeek={seekTo} isActive={activeId === segment.id} />)}</div> : <div className="empty-state"><div className="empty-icon">◌</div><strong>{job?.stage === "completed" ? "暂无文字记录" : "文字记录还在准备中"}</strong><p>完成浏览器录音或音频转写后，课堂原文会显示在这里。</p><Link className="button button-secondary" href={`/lessons/${lesson.id}`}>返回课次工作台</Link></div>}</div></section>
  </main>;
}
