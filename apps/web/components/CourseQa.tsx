"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";

type Citation = { id: number; lesson_id: string; lesson_title: string; start_ms: number; snippet: string };
type Answer = { answer: string; citations: Citation[] };

function time(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function CourseQa({ courseId }: { courseId: string }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [chunkCount, setChunkCount] = useState<number | null>(null);
  const [configured, setConfigured] = useState(true);
  const [busy, setBusy] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    request<{ chunk_count: number; configured: boolean }>(`/courses/${courseId}/index-status`)
      .then((result) => { setChunkCount(result.chunk_count); setConfigured(result.configured); })
      .catch((error) => setMessage(errorMessage(error)));
  }, [courseId]);

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (busy || question.trim().length < 2) return;
    setBusy(true); setMessage(""); setAnswer(null);
    try {
      setAnswer(await request<Answer>(`/courses/${courseId}/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      }));
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function rebuild() {
    if (rebuilding) return;
    setRebuilding(true); setMessage("");
    try {
      await request(`/courses/${courseId}/reindex`, { method: "POST" });
      setMessage("已开始整理课程资料，稍后刷新页面查看索引状态。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setRebuilding(false); }
  }

  const evidence = answer?.citations.reduce<(Citation & { ids: number[] })[]>((groups, item) => {
    const existing = groups.find((group) => group.lesson_id === item.lesson_id && group.start_ms === item.start_ms && group.snippet === item.snippet);
    if (existing) existing.ids.push(item.id);
    else groups.push({ ...item, ids: [item.id] });
    return groups;
  }, []) ?? [];

  return <section className="panel course-qa">
    <div className="panel-header qa-header"><div><span className="qa-eyebrow">课程问答</span><h2>问一问这门课</h2></div><span className="qa-index-count">{chunkCount === null ? "正在读取资料" : `${chunkCount} 段可检索内容`}</span></div>
    <div className="panel-body qa-body">
      <p className="qa-intro">输入想了解的问题，回答会标明对应课次与录音时间。</p>
      <form className="qa-form" onSubmit={ask}>
        <input className="field qa-input" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} placeholder="例如：二叉树有哪些性质？" aria-label="向这门课提问" />
        <button className="button button-primary qa-submit" disabled={busy || question.trim().length < 2}>{busy ? "查找中…" : "提问"}</button>
      </form>
      {chunkCount === 0 && <p className="qa-hint">这门课还没有问答索引。已有文字记录可以点击下方按钮整理。</p>}
      {!configured && <p className="notice">课程问答需要在后端配置 DASHSCOPE_API_KEY 和 DEEPSEEK_API_KEY。</p>}
      <button type="button" className="button button-quiet qa-rebuild" disabled={rebuilding} onClick={rebuild}>{rebuilding ? "提交中…" : "整理或更新课程资料"}</button>
      {message && <div className="notice qa-notice" role="status">{message}</div>}
      {answer && <div className="qa-result" aria-live="polite">
        <div className="qa-answer-heading"><span className="qa-answer-mark" aria-hidden="true">✦</span><h3>回答</h3></div>
        <div className="qa-answer-text">{answer.answer.split("\n\n").map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>
        {answer.citations.length > 0 && <details className="qa-evidence">
          <summary><span>查看回答依据</span><span className="qa-evidence-count">{evidence.length} 处来源</span><span className="qa-chevron" aria-hidden="true">⌄</span></summary>
          <div className="qa-evidence-list">{evidence.map((item) => <Link className="qa-evidence-item" key={item.id} href={`/lessons/${item.lesson_id}/transcript?t=${item.start_ms}`}><span className="qa-evidence-main"><strong>{item.lesson_title}<span> · {time(item.start_ms)}</span></strong><span className="qa-evidence-snippet">{item.snippet}</span><span className="qa-evidence-refs">对应回答引用：{item.ids.map((id) => `[${id}]`).join(" ")}</span></span><span className="qa-evidence-arrow" aria-hidden="true">↗</span></Link>)}</div>
        </details>}
      </div>}
    </div>
  </section>;
}
