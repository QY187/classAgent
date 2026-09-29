"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";

const stageLabel: Record<string, string> = { queued: "等待处理", transcribing: "正在转写", completed: "保存完成", failed: "处理失败" };
type Lesson = { id: string; course_id: string; title: string; lesson_date?: string | null; status: string };
type Job = { id: string; lesson_id: string; stage: string; progress: number; error_message?: string | null };
type Segment = { id: string; speaker: string; start_ms: number; end_ms: number; text: string; source: string };
type TranscriptChunk = { start_ms: number; end_ms: number; text: string };
type Summary = { id: string; lesson_id: string; status: string; content?: string | null; provider: string; error_message?: string | null };
type SummaryContent = {
  overview?: string;
  topics?: { title: string; time_range?: string; points?: string[]; source_indexes?: number[] }[];
  key_concepts?: { term: string; definition: string; source_indexes?: number[] }[];
  examples?: { title: string; explanation: string; source_indexes?: number[] }[];
  assignments?: string[];
  to_verify?: string[];
};
type RecognitionResult = { isFinal: boolean; 0: { transcript: string }; length: number };
type RecognitionEvent = Event & { resultIndex: number; results: { [index: number]: RecognitionResult; length: number } };
type Recognition = { lang: string; continuous: boolean; interimResults: boolean; onresult: ((event: RecognitionEvent) => void) | null; onerror: (() => void) | null; onend: (() => void) | null; start: () => void; stop: () => void; abort: () => void };
type RecognitionConstructor = new () => Recognition;

declare global { interface Window { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor } }

function formatTime(ms: number) { const seconds = Math.floor(ms / 1000); return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`; }

export default function LessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [recordingUrl, setRecordingUrl] = useState<string | null>(null);
  const [recordingName, setRecordingName] = useState("");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [message, setMessage] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const recognitionRef = useRef<Recognition | null>(null);
  const recognitionActiveRef = useRef(false);
  const recognitionFinishedRef = useRef<Promise<void> | null>(null);
  const transcriptChunksRef = useRef<TranscriptChunk[]>([]);
  const pendingTranscriptRef = useRef("");
  const segmentStartRef = useRef(0);
  const recordingStartedAtRef = useRef<number | null>(null);

  async function load() {
    try {
      setLesson(await request<Lesson>(`/lessons/${lessonId}`));
      try { setJob(await request<Job>(`/lessons/${lessonId}/jobs/latest`)); } catch { setJob(null); }
      try { setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`)); } catch { setSegments([]); }
      try { setSummary(await request<Summary>(`/lessons/${lessonId}/summary`)); } catch { setSummary(null); }
    } catch (error) { setMessage(errorMessage(error)); }
  }

  useEffect(() => { if (lessonId) load(); }, [lessonId]);
  useEffect(() => { if ((!job || ["completed", "failed"].includes(job.stage)) && (!summary || ["completed", "failed"].includes(summary.status))) return; const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer); }, [job?.stage, summary?.status, lessonId]);

  async function uploadFile(file: File, browserTranscript?: string) {
    if (uploading) return;
    setUploading(true); setMessage("音频上传中，请稍候…");
    try {
      const body = new FormData(); body.append("file", file);
      if (browserTranscript?.trim()) body.append("browser_transcript", browserTranscript.trim());
      setJob(await request<Job>(`/lessons/${lessonId}/audio`, { method: "POST", body }));
      setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`));
      setLesson(await request<Lesson>(`/lessons/${lessonId}`));
      try { setSummary(await request<Summary>(`/lessons/${lessonId}/summary`)); } catch { setSummary(null); }
      setLiveTranscript("");
      setMessage(browserTranscript?.trim() && browserTranscript !== "[]"
        ? "录音和浏览器识别的文字已保存。"
        : "音频已保存。没有浏览器识别文字，因此不会生成文字记录。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setUploading(false); }
  }

  function recordingElapsedMs() {
    return recordingStartedAtRef.current === null ? 0 : Math.max(0, Date.now() - recordingStartedAtRef.current);
  }

  function refreshLiveTranscript() {
    const text = [...transcriptChunksRef.current.map((chunk) => chunk.text), pendingTranscriptRef.current].filter(Boolean).join("");
    setLiveTranscript(text);
  }

  function addTranscriptChunk(text: string, endMs: number) {
    const cleanText = text.trim();
    if (!cleanText) return;
    const startMs = segmentStartRef.current;
    transcriptChunksRef.current.push({ start_ms: startMs, end_ms: Math.max(startMs + 1, endMs), text: cleanText });
    segmentStartRef.current = Math.max(startMs + 1, endMs);
  }

  function flushPendingAtMinute(elapsedMs: number) {
    if (pendingTranscriptRef.current.trim() && elapsedMs - segmentStartRef.current >= 60_000) {
      addTranscriptChunk(pendingTranscriptRef.current, elapsedMs);
      pendingTranscriptRef.current = "";
      refreshLiveTranscript();
    }
  }

  function consumeFinalTranscript(text: string, elapsedMs: number) {
    flushPendingAtMinute(elapsedMs);
    let pending = `${pendingTranscriptRef.current}${text}`;
    while (pending) {
      const sentence = pending.match(/^(.+?[。！？!?；;])/);
      if (!sentence) break;
      addTranscriptChunk(sentence[1], elapsedMs);
      pending = pending.slice(sentence[1].length);
    }
    pendingTranscriptRef.current = pending;
    refreshLiveTranscript();
  }

  function finalizeTranscript() {
    const elapsedMs = recordingElapsedMs();
    if (pendingTranscriptRef.current.trim()) addTranscriptChunk(pendingTranscriptRef.current, elapsedMs);
    pendingTranscriptRef.current = "";
    refreshLiveTranscript();
    return JSON.stringify(transcriptChunksRef.current);
  }

  async function uploadAudio(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) await uploadFile(file);
    event.target.value = "";
  }

  async function requestSummary() {
    if (summaryLoading || !segments.length) return;
    setSummaryLoading(true); setMessage("正在生成智能纪要，请稍候…");
    try {
      setSummary(await request<Summary>(`/lessons/${lessonId}/summary`, { method: "POST" }));
      setMessage("纪要已加入生成队列。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setSummaryLoading(false); }
  }

  function parseSummaryContent(content?: string | null): SummaryContent | null {
    if (!content) return null;
    try { return JSON.parse(content) as SummaryContent; } catch { return null; }
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setMessage("当前浏览器不支持录音，请改用音频文件上传。"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const RecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = RecognitionAPI ? new RecognitionAPI() : null;
      chunksRef.current = []; streamRef.current = stream; recorderRef.current = recorder;
      transcriptChunksRef.current = []; pendingTranscriptRef.current = ""; segmentStartRef.current = 0; recordingStartedAtRef.current = Date.now(); setLiveTranscript("");
      if (recognition) {
        recognition.lang = "zh-CN"; recognition.continuous = true; recognition.interimResults = true;
        recognition.onresult = (event) => {
          let interim = "";
          for (let index = event.resultIndex; index < event.results.length; index += 1) {
            const result = event.results[index];
            if (result.isFinal) consumeFinalTranscript(result[0].transcript, recordingElapsedMs());
            else interim += result[0].transcript;
          }
          setLiveTranscript(`${transcriptChunksRef.current.map((chunk) => chunk.text).join("")}${pendingTranscriptRef.current}${interim}`);
        };
        recognition.onerror = () => setMessage("浏览器语音识别暂时中断，录音仍会继续保存。");
        recognition.onend = () => { if (recognitionActiveRef.current) { try { recognition.start(); } catch { /* 浏览器正在重启识别 */ } } };
        recognitionRef.current = recognition; recognitionActiveRef.current = true;
        try { recognition.start(); } catch { setMessage("浏览器语音识别无法启动，录音仍会继续保存。"); }
      } else {
        setMessage("当前浏览器不支持实时转写，录音仍会继续保存。");
      }
      recorder.ondataavailable = (event) => { if (event.data.size > 0) chunksRef.current.push(event.data); };
      recorder.onstop = async () => {
        await recognitionFinishedRef.current;
        recognitionFinishedRef.current = null;
        const type = recorder.mimeType || "audio/webm";
        const file = new File([new Blob(chunksRef.current, { type })], `classagent-recording-${Date.now()}.webm`, { type });
        setRecordingUrl((previous) => { if (previous) URL.revokeObjectURL(previous); return URL.createObjectURL(file); });
        setRecordingName(file.name);
        streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null;
        recognitionRef.current = null;
        await uploadFile(file, finalizeTranscript());
      };
      recorder.start(1000); setRecording(true); setRecordingSeconds(0); setMessage("正在录音并尝试浏览器实时转写，请保持当前页面打开。");
      recordingTimerRef.current = window.setInterval(() => setRecordingSeconds((seconds) => { const next = seconds + 1; flushPendingAtMinute(next * 1000); return next; }), 1000);
    } catch (error) { setMessage(error instanceof DOMException && error.name === "NotAllowedError" ? "麦克风权限被拒绝，请允许浏览器访问麦克风后重试。" : "无法启动录音，请改用音频文件上传。"); }
  }

  function stopRecording() {
    if (!recorderRef.current || recorderRef.current.state === "inactive") return;
    recorderRef.current.stop();
    recognitionActiveRef.current = false;
    if (recognitionRef.current) {
      const recognition = recognitionRef.current;
      recognitionFinishedRef.current = new Promise((resolve) => {
        const previousOnEnd = recognition.onend;
        const timeout = window.setTimeout(resolve, 1500);
        recognition.onend = () => { previousOnEnd?.(); window.clearTimeout(timeout); resolve(); };
      });
      recognition.stop();
    }
    if (recordingTimerRef.current !== null) window.clearInterval(recordingTimerRef.current);
    recordingTimerRef.current = null; setRecording(false); setMessage("录音已结束，正在上传…");
  }

  function downloadTranscript() {
    const text = segments.length
      ? segments.map((segment) => `[${formatTime(segment.start_ms)}] ${segment.speaker}\n${segment.text}`).join("\n\n")
      : liveTranscript;
    if (!text.trim()) { setMessage("当前还没有可下载的文字记录。"); return; }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${lesson?.title || "课堂"}-文字记录.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => () => { if (recordingTimerRef.current !== null) window.clearInterval(recordingTimerRef.current); recognitionActiveRef.current = false; recognitionRef.current?.stop(); recorderRef.current?.stop(); streamRef.current?.getTracks().forEach((track) => track.stop()); if (recordingUrl) URL.revokeObjectURL(recordingUrl); }, [recordingUrl]);

  if (!lesson) return <main className="content"><div className="empty-state"><p role="status">{message || "正在加载课次…"}</p>{message && <><Link href="/">返回课程库</Link><button className="button button-secondary" onClick={load}>重试</button></>}</div></main>;
  const progress = job?.progress ?? 0;
  const recordingTime = `${String(Math.floor(recordingSeconds / 60)).padStart(2, "0")}:${String(recordingSeconds % 60).padStart(2, "0")}`;
  const summaryContent = parseSummaryContent(summary?.content);
  return <main className="content"><Link className="back-link" href={`/courses/${lesson.course_id}`}>← 返回课程</Link><div className="page-heading"><div><div className="eyebrow">课次详情</div><h1>{lesson.title}</h1><p>{lesson.lesson_date || "未设置日期"} · 课堂资料</p></div><label className="button button-primary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading || recording} />{uploading ? "上传中…" : "上传课堂音频"}</label></div>{message && <div className="notice" style={{ marginBottom: 18 }}>{message}</div>}<section className="panel summary-panel"><div className="panel-header"><div><h2>智能纪要</h2><span className="summary-caption">根据本节课文字记录生成，可重新生成</span></div><div style={{ display: "flex", alignItems: "center", gap: 10 }}>{summary && <span className={`pill pill-${summary.status}`}>{summary.status === "completed" ? "已完成" : summary.status === "generating" ? "生成中" : summary.status === "failed" ? "生成失败" : "等待生成"}</span>}<button className="button button-secondary" onClick={requestSummary} disabled={!segments.length || summaryLoading || summary?.status === "generating"}>{summaryLoading || summary?.status === "queued" || summary?.status === "generating" ? "生成中…" : summary ? "重新生成" : "生成智能纪要"}</button></div></div><div className="panel-body">{summary?.status === "completed" && summaryContent ? <div className="summary-content"><div className="summary-overview"><div className="summary-label">一句话概览</div><p>{summaryContent.overview || "暂无概览"}</p></div>{Boolean(summaryContent.topics?.length) && <div className="summary-section"><div className="summary-label">课堂主题</div>{summaryContent.topics?.map((topic, index) => <div className="summary-topic" key={`${topic.title}-${index}`}><div className="summary-topic-head"><strong>{topic.title}</strong>{topic.time_range && <span>{topic.time_range}</span>}</div><ul>{topic.points?.map((point) => <li key={point}>{point}</li>)}</ul></div>)}</div>}{Boolean(summaryContent.key_concepts?.length) && <div className="summary-section"><div className="summary-label">重点知识</div><div className="summary-concepts">{summaryContent.key_concepts?.map((concept) => <div className="summary-concept" key={concept.term}><strong>{concept.term}</strong><span>{concept.definition}</span></div>)}</div></div>}{Boolean(summaryContent.examples?.length) && <div className="summary-section"><div className="summary-label">例题与案例</div>{summaryContent.examples?.map((example) => <div className="summary-note" key={example.title}><strong>{example.title}</strong><span>{example.explanation}</span></div>)}</div>}<div className="summary-columns">{Boolean(summaryContent.assignments?.length) && <div className="summary-section"><div className="summary-label">作业与预告</div><ul>{summaryContent.assignments?.map((item) => <li key={item}>{item}</li>)}</ul></div>}{Boolean(summaryContent.to_verify?.length) && <div className="summary-section"><div className="summary-label">待核对</div><ul>{summaryContent.to_verify?.map((item) => <li key={item}>{item}</li>)}</ul></div>}</div></div> : summary?.status === "failed" ? <div className="notice">{summary.error_message || "纪要生成失败，请重试。"}</div> : summary?.status === "queued" || summary?.status === "generating" ? <div className="summary-placeholder"><div className="empty-icon">✦</div><strong>正在整理这节课的重点</strong><p>纪要生成完成后会自动出现在这里。</p></div> : <div className="summary-placeholder"><div className="empty-icon">✦</div><strong>{segments.length ? "生成一份可复习的课堂纪要" : "先完成文字记录"}</strong><p>{segments.length ? "提取课程主题、关键概念、例题、作业和待核对内容。" : "浏览器录音并识别出文字后，即可生成纪要。"}</p></div>}</div></section><div className="detail-grid"><section className="panel"><div className="panel-header"><h2>文字记录</h2><div style={{ display: "flex", alignItems: "center", gap: 10 }}>{job && <span className={`pill pill-${job.stage}`}>{stageLabel[job.stage] || job.stage}</span>}{(segments.length > 0 || liveTranscript) && <button className="button button-quiet" onClick={downloadTranscript}>下载文字记录</button>}</div></div><div className="panel-body">{recording && liveTranscript && <div className="notice" style={{ marginBottom: 18 }}><strong>浏览器实时转写</strong><div style={{ marginTop: 7, whiteSpace: "pre-wrap" }}>{liveTranscript}</div></div>}{job && job.stage !== "completed" && <div style={{ marginBottom: 18 }}><div style={{ display: "flex", justifyContent: "space-between", color: "#6b7280", fontSize: 12 }}><span>{stageLabel[job.stage] || job.stage}</span><span>{progress}%</span></div><div className="job-progress"><span style={{ width: `${progress}%` }} /></div>{job.error_message && <div className="notice" style={{ marginTop: 10 }}>{job.error_message}</div>}</div>}{segments.length ? <div className="transcript">{segments.map((segment) => <div className="transcript-segment" key={segment.id}><div><div className="speaker">{segment.speaker}</div><div className="timecode">{formatTime(segment.start_ms)}</div></div><div className="transcript-text">{segment.text}</div></div>)}</div> : <div className="empty-state"><div className="empty-icon">◌</div><strong>{job?.stage === "completed" ? "暂无浏览器识别文字" : "录音并完成浏览器识别后生成文字记录"}</strong><p>只有浏览器识别确认的文字会保存在这里；单独上传音频不会自动转写。</p></div>}</div></section><aside className="panel"><div className="panel-header"><h2>音频与处理</h2></div><div className="panel-body"><div className="upload-box"><div style={{ fontSize: 28 }}>♫</div><strong>{recording ? `正在录音 ${recordingTime}` : "录音或上传这节课的音频"}</strong><p>{recording ? "录音结束后会自动保存音频和浏览器识别的文字。" : "可以直接使用浏览器麦克风，也可以选择已有文件。"}</p>{recording ? <button className="button button-primary" onClick={stopRecording} disabled={uploading}>结束录音</button> : <div style={{ display: "flex", justifyContent: "center", gap: 9, flexWrap: "wrap" }}><button className="button button-primary" onClick={startRecording} disabled={uploading}>开始录音</button><label className="button button-secondary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading} />选择音频文件</label></div>}</div>{recordingUrl && <div style={{ marginTop: 16, padding: 12, border: "1px solid #e7e9ee", borderRadius: 9 }}><div style={{ color: "#596274", fontSize: 12, marginBottom: 8 }}>本地录音文件：{recordingName}</div><audio controls src={recordingUrl} style={{ width: "100%" }} /><a className="button button-secondary" href={recordingUrl} download={recordingName} style={{ display: "inline-block", marginTop: 10 }}>下载录音文件</a></div>}<div className="notice" style={{ marginTop: 16 }}>录音时浏览器会尝试实时识别中文。若浏览器不支持或识别失败，仍会保存音频，但不会生成文字记录。单独上传已有音频也不会自动转写。</div></div></aside></div></main>;
}
