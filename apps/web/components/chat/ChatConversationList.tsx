"use client";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { ChatLesson, Conversation } from "../../lib/chat";

export default function ChatConversationList({ lesson, selectedId, onSelect, revision }: {
  lesson: ChatLesson; selectedId: string | null; onSelect: (item: Conversation) => void; revision: number;
}) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setError("");
    request<Conversation[]>(`/chat/lessons/${lesson.id}/conversations`, { signal: controller.signal }).then(setItems)
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [lesson.id, revision, retry]);
  async function create() {
    if (creating) return;
    setCreating(true); setError("");
    try {
      const item = await request<Conversation>(`/chat/lessons/${lesson.id}/conversations`, { method: "POST" });
      setItems((current) => [item, ...current]); onSelect(item);
    } catch (err) { setError(errorMessage(err)); }
    finally { setCreating(false); }
  }
  return <div className="chat-conversations"><button className="chat-new-conversation" disabled={creating} onClick={create}>{creating ? "正在创建…" : "＋ 新建对话"}</button>
    {error && <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-quiet" onClick={() => setRetry((value) => value + 1)}>重试</button></div>}
    {loading ? <p className="chat-tree-hint">读取对话…</p> : items.length ? items.map((item) => <button key={item.id} className={`chat-conversation-link${item.id === selectedId ? " active" : ""}`} aria-current={item.id === selectedId ? "true" : undefined} title={item.title} onClick={() => onSelect(item)}><span aria-hidden="true">◌</span><span>{item.title}</span></button>) : !error && <p className="chat-tree-hint">还没有对话</p>}
  </div>;
}
