"use client";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatConversationList({ targetId, scope, selectedId, onSelect, revision, createOnly = false, renderHeading, collapsed = false }: {
  renderHeading?: (action: ReactNode) => ReactNode; collapsed?: boolean;
  targetId: string; scope: Conversation["scope"]; selectedId: string | null; onSelect: (item: Conversation) => void; revision: number; createOnly?: boolean;
}) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [retry, setRetry] = useState(0);
  const endpoint = scope === "global" ? "/chat/conversations" : `/chat/${scope === "course" ? "courses" : "lessons"}/${targetId}/conversations`;
  useEffect(() => {
    const controller = new AbortController(); setError("");
    request<Conversation[]>(scope === "course" ? `${endpoint}?include_lessons=true` : endpoint, { signal: controller.signal }).then((items) => { if (!controller.signal.aborted) setItems(items); })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [endpoint, revision, retry]);
  async function create() {
    if (creating) return;
    setCreating(true); setError("");
    try {
      const item = await request<Conversation>(endpoint, { method: "POST" });
      setItems((current) => [item, ...current]); onSelect(item);
    } catch (err) { setError(errorMessage(err)); }
    finally { setCreating(false); }
  }
  const actionLabel = scope === "global" ? "新建主对话" : scope === "course" ? "新建课程对话" : "新建课次对话";
  const action = <button type="button" className={renderHeading ? "chat-heading-action" : "chat-new-conversation"} aria-label={actionLabel} title={actionLabel} disabled={creating || loading} onClick={create}>{renderHeading ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12.5 4.5h-5A3 3 0 0 0 4.5 7.5v9a3 3 0 0 0 3 3h9a3 3 0 0 0 3-3v-5"/><path d="m18 3.5 2.5 2.5-8.75 8.75-3.25.75.75-3.25Z"/></svg> : creating ? "正在创建…" : "＋ 新对话"}</button>;
  return <div className={`chat-conversations ${scope}${renderHeading ? " with-heading" : ""}`}>{renderHeading ? renderHeading(action) : action}
    {!collapsed && <div className={scope === "course" && renderHeading ? "chat-course-conversations" : undefined}>{error && <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-quiet" onClick={() => setRetry((value) => value + 1)}>重试</button></div>}
    {!createOnly && (loading ? <p className="chat-tree-hint">读取对话…</p> : items.length ? items.map((item) => <button key={item.id} className={`chat-conversation-link${item.id === selectedId ? " active" : ""}`} aria-current={item.id === selectedId ? "true" : undefined} title={item.title} onClick={() => onSelect(item)}><span aria-hidden="true">◌</span><span>{item.title}</span></button>) : !error && <p className="chat-tree-hint">还没有对话</p>)}</div>}
  </div>;
}
