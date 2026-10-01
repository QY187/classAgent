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

  return <section className="panel" style={{ marginBottom: 20 }}>
    <div className="panel-header"><h2>问一问这门课</h2><span>{chunkCount === null ? "加载中" : `${chunkCount} 段可检索内容`}</span></div>
    <div className="panel-body">
      <p style={{ marginTop: 0 }}>综合这门课的文字记录提问，回答会标明对应课次与录音时间。</p>
      <form onSubmit={ask} style={{ display: "flex", gap: 10 }}>
        <input className="field" style={{ flex: 1 }} value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} placeholder="例如：老师在哪几节课讲过二叉树遍历？" aria-label="向这门课提问" />
        <button className="button button-primary" disabled={busy || question.trim().length < 2}>{busy ? "查找中…" : "提问"}</button>
      </form>
      {chunkCount === 0 && <p>这门课还没有问答索引。已有文字记录可以点击下方按钮整理。</p>}
      {!configured && <p className="notice">课程问答需要在后端配置 DASHSCOPE_API_KEY 和 DEEPSEEK_API_KEY。</p>}
      <button type="button" className="button button-quiet" disabled={rebuilding} onClick={rebuild} style={{ marginTop: 8 }}>{rebuilding ? "提交中…" : "整理或更新课程资料"}</button>
      {message && <div className="notice" role="status">{message}</div>}
      {answer && <div style={{ marginTop: 20 }} aria-live="polite">
        <h3>回答</h3>
        {answer.answer.split("\n\n").map((paragraph, index) => <p key={index}>{paragraph}</p>)}
        {answer.citations.length > 0 && <div><h3>依据</h3><div className="lesson-list">{answer.citations.map((item) => <Link className="lesson-row" key={item.id} href={`/lessons/${item.lesson_id}/transcript?t=${item.start_ms}`}><span className="lesson-index">{item.id}</span><span className="lesson-main"><strong>{item.lesson_title} · {time(item.start_ms)}</strong><span className="lesson-date">{item.snippet}</span></span><span className="lesson-go">→</span></Link>)}</div></div>}
      </div>}
    </div>
  </section>;
}
