"use client";

import { useState } from "react";
import { errorMessage, request } from "../../../lib/api";

export type Lesson = { id: string; course_id: string; title: string; lesson_date?: string | null; status: string };
export type Job = { id: string; lesson_id: string; stage: string; progress: number; error_message?: string | null };
export type Segment = { id: string; speaker: string; start_ms: number; end_ms: number; text: string; source: string };
export type Summary = { id: string; lesson_id: string; status: string; content?: string | null; provider: string; error_message?: string | null };
export type SummaryContent = {
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

export const stageLabel: Record<string, string> = { queued: "等待处理", transcribing: "正在转写", completed: "处理完成", failed: "处理失败" };

export function formatTime(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function parseSummaryContent(content?: string | null): SummaryContent | null {
  if (!content) return null;
  try { return JSON.parse(content) as SummaryContent; } catch { return null; }
}

function SourceIndexes({ indexes }: { indexes?: number[] }) {
  if (!indexes?.length) return null;
  return <span className="summary-sources">来源片段 {indexes.join("、")}</span>;
}

export function SummaryContentView({ content }: { content: SummaryContent }) {
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

export function TranscriptSegmentItem({ segment, onSave, displayName, onMerge }: { segment: Segment; onSave: (id: string, text: string) => Promise<void>; displayName?: string; onMerge?: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(segment.text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    if (!draft.trim()) { setError("文字记录不能为空。"); return; }
    setSaving(true); setError("");
    try { await onSave(segment.id, draft.trim()); setEditing(false); } catch (saveError) { setError(errorMessage(saveError)); } finally { setSaving(false); }
  }
  return <div className="transcript-segment"><div><div className="speaker">{displayName ?? segment.speaker}</div><div className="timecode">{formatTime(segment.start_ms)}</div></div><div>{editing ? <div className="transcript-edit-form"><textarea className="field transcript-edit-input" aria-label={`编辑 ${formatTime(segment.start_ms)} 的文字记录`} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={10000} rows={3} disabled={saving} />{error && <div className="transcript-edit-error" role="alert">{error}</div>}<div className="transcript-edit-actions"><button className="button button-primary" onClick={save} disabled={saving}>{saving ? "保存中…" : "保存"}</button><button className="button button-secondary" onClick={() => { setDraft(segment.text); setError(""); setEditing(false); }} disabled={saving}>取消</button></div></div> : <><div className="transcript-text">{segment.text}</div><div className="transcript-edit-actions">{segment.source === "manual" && <span className="transcript-edited">已人工校正</span>}<button className="button button-quiet transcript-edit-button" onClick={() => { setDraft(segment.text); setError(""); setEditing(true); }}>编辑</button>{onMerge && <button className="button button-quiet transcript-edit-button" onClick={onMerge}>合并下段</button>}</div></>}</div></div>;
}

export async function saveSegment(lessonId: string, segmentId: string, text: string) {
  return request<Segment>(`/lessons/${lessonId}/transcript/${segmentId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
}
