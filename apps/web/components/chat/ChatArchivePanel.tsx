"use client";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { ChatSearchResult, Conversation } from "../../lib/chat";
import ChatArchiveButton from "./ChatArchiveButton";

export default function ChatArchivePanel({ revision, onSelect, onRestored }: {
  revision: number; onSelect: (item: Conversation) => void; onRestored: (item: Conversation) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ChatSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError("");
    request<ChatSearchResult[]>("/chat/archived", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setItems(result); })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, revision, retry]);
  return <section className="chat-archive-panel"><button className="chat-archive-toggle" aria-expanded={open} onClick={() => setOpen(!open)}><span className="chat-archive-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 3h18v5H3zM5 8v13h14V8M9 12h6" /></svg>已归档对话</span><svg className="chat-archive-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m6 4 4 4-4 4" /></svg></button>
    {open && <div><p className="chat-archive-description">内容已保留，可随时恢复</p>{loading ? <p role="status" className="chat-tree-hint">正在读取…</p> : error ? <div className="chat-tree-hint"><p role="alert">{error}</p><button onClick={() => setRetry(v => v + 1)}>重试</button></div> : items.length ? items.map(item => <div className="chat-archive-row" key={item.id}><button className="chat-search-hit" title={item.title} onClick={() => onSelect(item)}><strong>{item.title}</strong><span>{item.course_name}{item.lesson_title ? ` / ${item.lesson_title}` : ""}</span></button><ChatArchiveButton conversation={item} compact onChanged={(restored) => { setItems(current => current.filter(row => row.id !== item.id)); onRestored(restored); }} /></div>) : <p className="chat-tree-hint">还没有归档对话</p>}</div>}
  </section>;
}
