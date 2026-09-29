"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import { collectSpeechResults } from "../../../lib/speech-results";

const stageLabel: Record<string, string> = { queued: "等待处理", transcribing: "正在转写", completed: "保存完成", failed: "处理失败" };
type Lesson = { id: string; course_id: string; title: string; lesson_date?: string | null; status: string };
type Job = { id: string; lesson_id: string; stage: string; progress: number; error_message?: string | null };
type Segment = { id: string; speaker: string; start_ms: number; end_ms: number; text: string; source: string };
type TranscriptChunk = { start_ms: number; end_ms: number; text: string };
type Summary = { id: string; lesson_id: string; status: string; content?: string | null; provider: string; error_message?: string | null };
type SummaryContent = {
  overview?: string;
  learning_goals?: string[];
  chapter_flow?: { title: string; time_range?: string; summary?: string; source_indexes?: number[] }[];
  topics?: { title: string; time_range?: string; summary?: string; points?: string[]; takeaway?: string; source_indexes?: number[] }[];
  key_concepts?: { term: string; definition: string; importance?: string; source_indexes?: number[] }[];
  key_takeaways?: string[];
  examples?: { title: string; context?: string; explanation: string; conclusion?: string; source_indexes?: number[] }[];
  teacher_emphasis?: string[];
  assignments?: string[];
  questions?: string[];
  to_verify?: string[];
  keywords?: string[];
  review_questions?: string[];
};
type RecognitionResult = { isFinal: boolean; 0: { transcript: string }; length: number };
type RecognitionEvent = Event & { resultIndex: number; results: { [index: number]: RecognitionResult; length: number } };
type Recognition = { lang: string; continuous: boolean; interimResults: boolean; onresult: ((event: RecognitionEvent) => void) | null; onerror: (() => void) | null; onend: (() => void) | null; start: () => void; stop: () => void; abort: () => void };
type RecognitionConstructor = new () => Recognition;

declare global { interface Window { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor } }

function formatTime(ms: number) { const seconds = Math.floor(ms / 1000); return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`; }

function TranscriptSegmentItem({ segment, onSave }: { segment: Segment; onSave: (id: string, text: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(segment.text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (!draft.trim()) { setError("文字记录不能为空。"); return; }
    setSaving(true);
    setError("");
    try {
      await onSave(segment.id, draft.trim());
      setEditing(false);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  return <div className="transcript-segment">
    <div><div className="speaker">{segment.speaker}</div><div className="timecode">{formatTime(segment.start_ms)}</div></div>
    <div>{editing ? <div className="transcript-edit-form">
      <textarea className="field transcript-edit-input" aria-label={`编辑 ${formatTime(segment.start_ms)} 的文字记录`} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={10000} rows={3} disabled={saving} />
      {error && <div className="transcript-edit-error" role="alert">{error}</div>}
      <div className="transcript-edit-actions"><button className="button button-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存"}</button><button className="button button-secondary" onClick={() => { setDraft(segment.text); setError(""); setEditing(false); }} disabled={saving}>取消</button></div>
    </div> : <><div className="transcript-text">{segment.text}</div><div className="transcript-edit-actions">{segment.source === "manual" && <span className="transcript-edited">已人工校正</span>}<button className="button button-quiet transcript-edit-button" onClick={() => { setDraft(segment.text); setError(""); setEditing(true); }}>编辑</button></div></>}</div>
  </div>;
}

function SourceIndexes({ indexes }: { indexes?: number[] }) {
  if (!indexes?.length) return null;
  return <span className="summary-sources">来源片段 {indexes.join("、")}</span>;
}

function SummaryContentView({ content }: { content: SummaryContent }) {
  return <div className="summary-content">
    <div className="summary-overview"><div className="summary-label">课程概览</div><p>{content.overview || "暂无概览"}</p></div>
    {Boolean(content.learning_goals?.length) && <div className="summary-section"><div className="summary-label">本节学习目标</div><ul>{content.learning_goals?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
    {Boolean(content.chapter_flow?.length) && <div className="summary-section"><div className="summary-label">章节脉络</div><div className="summary-flow">{content.chapter_flow?.map((item, index) => <div className="summary-flow-item" key={`${item.title}-${index}`}><div className="summary-topic-head"><strong>{index + 1}. {item.title}</strong>{item.time_range && <span>{item.time_range}</span>}</div>{item.summary && <p>{item.summary}</p>}<SourceIndexes indexes={item.source_indexes} /></div>)}</div></div>}
    {Boolean(content.topics?.length) && <div className="summary-section"><div className="summary-label">主题与重点</div>{content.topics?.map((topic, index) => <div className="summary-topic" key={`${topic.title}-${index}`}><div className="summary-topic-head"><strong>{topic.title}</strong>{topic.time_range && <span>{topic.time_range}</span>}</div>{topic.summary && <p className="summary-topic-summary">{topic.summary}</p>}{Boolean(topic.points?.length) && <ul>{topic.points?.map((point, pointIndex) => <li key={`${point}-${pointIndex}`}>{point}</li>)}</ul>}{topic.takeaway && <div className="summary-takeaway"><strong>记住：</strong>{topic.takeaway}</div>}<SourceIndexes indexes={topic.source_indexes} /></div>)}</div>}
    {Boolean(content.key_concepts?.length) && <div className="summary-section"><div className="summary-label">核心概念</div><div className="summary-concepts">{content.key_concepts?.map((concept, index) => <div className="summary-concept" key={`${concept.term}-${index}`}><strong>{concept.term}</strong><span>{concept.definition}</span>{concept.importance && <small>{concept.importance}</small>}<SourceIndexes indexes={concept.source_indexes} /></div>)}</div></div>}
    {Boolean(content.key_takeaways?.length) && <div className="summary-section"><div className="summary-label">关键结论</div><ul>{content.key_takeaways?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
    {Boolean(content.examples?.length) && <div className="summary-section"><div className="summary-label">例题与案例</div>{content.examples?.map((example, index) => <div className="summary-note" key={`${example.title}-${index}`}><strong>{example.title}</strong>{example.context && <span><b>背景：</b>{example.context}</span>}<span><b>思路：</b>{example.explanation}</span>{example.conclusion && <span><b>结论：</b>{example.conclusion}</span>}<SourceIndexes indexes={example.source_indexes} /></div>)}</div>}
    {Boolean(content.teacher_emphasis?.length) && <div className="summary-section"><div className="summary-label">老师强调</div><ul>{content.teacher_emphasis?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
    <div className="summary-columns">{Boolean(content.assignments?.length) && <div className="summary-section"><div className="summary-label">作业与后续安排</div><ul>{content.assignments?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}{Boolean(content.questions?.length) && <div className="summary-section"><div className="summary-label">课堂问题</div><ul>{content.questions?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}</div>
    <div className="summary-columns">{Boolean(content.review_questions?.length) && <div className="summary-section"><div className="summary-label">复习自测</div><ol>{content.review_questions?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ol></div>}{Boolean(content.to_verify?.length) && <div className="summary-section"><div className="summary-label">待核对内容</div><ul>{content.to_verify?.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}</div>
    {Boolean(content.keywords?.length) && <div className="summary-keywords"><div className="summary-label">关键词</div><div>{content.keywords?.map((keyword) => <span key={keyword}>{keyword}</span>)}</div></div>}
  </div>;
}

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
  const acceptedFinalIndicesRef = useRef<Set<number>>(new Set());
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
      const nextJob = await request<Job>(`/lessons/${lessonId}/audio`, { method: "POST", body });
      setJob(nextJob);
      setSegments(await request<Segment[]>(`/lessons/${lessonId}/transcript`));
      setLesson(await request<Lesson>(`/lessons/${lessonId}`));
      try { setSummary(await request<Summary>(`/lessons/${lessonId}/summary`)); } catch { setSummary(null); }
      setLiveTranscript("");
      setMessage(nextJob.stage === "queued"
        ? "音频已保存，正在等待阿里云录音文件转写。"
        : "录音和浏览器识别的文字已保存。");
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

  async function saveSegmentText(segmentId: string, text: string) {
    const updated = await request<Segment>(`/lessons/${lessonId}/transcript/${segmentId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    setSegments((current) => current.map((segment) => segment.id === segmentId ? updated : segment));
    try {
      const nextSummary = await request<Summary>(`/lessons/${lessonId}/summary`);
      setSummary(nextSummary);
      setMessage(nextSummary.status === "stale" ? "文字已保存。请重新生成智能纪要，更新其中的内容。" : "文字已保存。");
    } catch {
      setSummary(null);
      setMessage("文字已保存。");
    }
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
      transcriptChunksRef.current = []; pendingTranscriptRef.current = ""; segmentStartRef.current = 0; recordingStartedAtRef.current = Date.now(); acceptedFinalIndicesRef.current.clear(); setLiveTranscript("");
      if (recognition) {
        recognition.lang = "zh-CN"; recognition.continuous = true; recognition.interimResults = true;
        recognition.onresult = (event) => {
          const { finalTexts, interim } = collectSpeechResults(event.results, acceptedFinalIndicesRef.current);
          for (const text of finalTexts) consumeFinalTranscript(text, recordingElapsedMs());
          setLiveTranscript(`${transcriptChunksRef.current.map((chunk) => chunk.text).join("")}${pendingTranscriptRef.current}${interim}`);
        };
        recognition.onerror = () => setMessage("浏览器语音识别暂时中断，录音仍会继续保存。");
        recognition.onend = () => { if (recognitionActiveRef.current) { acceptedFinalIndicesRef.current.clear(); try { recognition.start(); } catch { /* 浏览器正在重启识别 */ } } };
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
  const hasContent = segments.length > 0 || Boolean(liveTranscript) || recording || Boolean(job);
  return <main className="content lesson-workspace">
    <Link className="back-link" href={`/courses/${lesson.course_id}`}>← 返回课程</Link>
    <div className="page-heading"><div><div className="eyebrow">课次工作台</div><h1>{lesson.title}</h1><p>{lesson.lesson_date || "未设置日期"} · 课堂资料</p></div><label className="button button-secondary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading || recording} />{uploading ? "上传中…" : "上传课堂音频"}</label></div>
    {message && <div className="notice" style={{ marginBottom: 18 }}>{message}</div>}
    <section className={`recording-hero ${recording ? "is-recording" : ""}`}><div className="recording-hero-icon">{recording ? "●" : "♫"}</div><div className="recording-hero-copy"><div className="eyebrow">{recording ? "正在记录课堂" : hasContent ? "继续整理课堂资料" : "开始建立课堂资料"}</div><h2>{recording ? `录音中 ${recordingTime}` : hasContent ? "这节课的内容已准备好" : "从一次录音开始"}</h2><p>{recording ? "你可以边说边查看浏览器实时文字记录，结束后会自动保存音频。" : hasContent ? "文字记录和智能纪要已经分开整理，选择一个入口继续。" : "支持浏览器录音和已有音频上传，处理后可查看文字记录与智能纪要。"}</p></div><div className="recording-hero-action">{recording ? <button className="button button-primary" onClick={stopRecording} disabled={uploading}>结束录音</button> : <button className="button button-primary" onClick={startRecording} disabled={uploading}>开始录音</button>}</div></section>
    {recording && <section className="panel live-panel"><div className="panel-header"><div><h2>实时文字记录</h2><span className="summary-caption">浏览器识别到的内容会即时显示</span></div><span className="live-indicator"><i /> 实时</span></div><div className="panel-body">{liveTranscript ? <div className="live-transcript">{liveTranscript}</div> : <div className="empty-state live-empty"><div className="empty-icon">◌</div><strong>等待你开始说话</strong><p>请保持页面打开，浏览器会尝试识别中文。</p></div>}</div></section>}
    {hasContent && !recording && <section className="workspace-entry-grid"><Link className="workspace-entry summary-entry" href={`/lessons/${lesson.id}/summary`}><div className="entry-icon">✦</div><div className="entry-copy"><div className="eyebrow">智能整理</div><h2>智能纪要</h2><p>查看课程概览、章节脉络、核心概念、老师强调和复习自测。</p><span className="entry-link">查看智能纪要 <b>→</b></span></div>{summary && <span className={`pill pill-${summary.status}`}>{summary.status === "completed" ? "已完成" : summary.status === "stale" ? "需更新" : summary.status === "generating" || summary.status === "queued" ? "生成中" : "待生成"}</span>}</Link><Link className="workspace-entry transcript-entry" href={`/lessons/${lesson.id}/transcript`}><div className="entry-icon">▤</div><div className="entry-copy"><div className="eyebrow">原始内容</div><h2>文字记录</h2><p>按时间和说话人阅读课堂原文，支持人工校正和下载。</p><span className="entry-link">查看文字记录 <b>→</b></span></div>{job && <span className={`pill pill-${job.stage}`}>{stageLabel[job.stage] || job.stage}</span>}</Link></section>}
    {recordingUrl && <section className="panel audio-preview-panel"><div className="panel-header"><div><h2>本地录音</h2><span className="summary-caption">录音文件已保存在浏览器中</span></div></div><div className="panel-body"><div className="audio-preview"><span>{recordingName}</span><audio controls src={recordingUrl} /><a className="button button-secondary" href={recordingUrl} download={recordingName}>下载录音</a></div></div></section>}
    {!recording && !hasContent && <section className="empty-workspace"><div className="empty-icon">◌</div><strong>还没有课堂内容</strong><p>点击“开始录音”边说边记录，或上传已有音频。</p><div><button className="button button-primary" onClick={startRecording} disabled={uploading}>开始录音</button><label className="button button-secondary upload-label"><input className="upload-input" type="file" accept="audio/*" onChange={uploadAudio} disabled={uploading} />选择音频文件</label></div></section>}
    {job && job.stage !== "completed" && <section className="panel processing-panel"><div className="panel-body"><div className="progress-label"><span>{stageLabel[job.stage] || job.stage}</span><span>{progress}%</span></div><div className="job-progress"><span style={{ width: `${progress}%` }} /></div>{job.error_message && <div className="notice" style={{ marginTop: 10 }}>{job.error_message}</div>}</div></section>}
  </main>;
}
