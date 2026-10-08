"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { errorMessage, request } from "../../lib/api";
import type { ChatHistory, Conversation } from "../../lib/chat";
import ChatMessageList from "./ChatMessageList";
import ChatComposer from "./ChatComposer";
import ChatTitleEditor from "./ChatTitleEditor";
import ChatDeleteButton from "./ChatDeleteButton";

export default function ChatThread({ conversationId, onLoaded, onChanged, onDeleted }: { conversationId: string; onLoaded: (item: Conversation) => void; onChanged: () => void; onDeleted: () => void }) {
  const [history, setHistory] = useState<ChatHistory | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const bottom = useRef<HTMLDivElement>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await request<ChatHistory>(`/chat/conversations/${conversationId}/messages`, { signal });
      if (signal?.aborted || !mounted.current) return;
      setHistory(result); onLoaded(result.conversation); setError("");
    } catch (err) { if (!signal?.aborted) setError(errorMessage(err)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [conversationId, onLoaded]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  useEffect(() => {
    if (!history?.conversation.generating || sending) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => void load(controller.signal), 2000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [history?.conversation.generating, load, sending]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [history?.messages.length]);
  async function send(content: string, retryRequest?: string) {
    if (sendingRef.current || !history) return false;
    sendingRef.current = true; setSending(true); setError("");
    const last = history.messages.at(-1);
    const requestId = retryRequest || (last?.role === "user" && last.content === content && last.status !== "completed" ? last.request_id : crypto.randomUUID());
    if (last?.request_id !== requestId) setHistory({ ...history, conversation: { ...history.conversation, generating: true }, messages: [...history.messages, {
      id: requestId, request_id: requestId, position: (last?.position || 0) + 1, role: "user", content, status: "pending", citations: [], error_message: null, created_at: new Date().toISOString(),
    }] });
    else setHistory({ ...history, conversation: { ...history.conversation, generating: true }, messages: history.messages.map((item) => item.request_id === requestId && item.role === "user" ? { ...item, status: "pending", error_message: null } : item) });
    try {
      const result = await request<ChatHistory>(`/chat/conversations/${conversationId}/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, request_id: requestId }),
      });
      if (mounted.current) { setHistory(result); onLoaded(result.conversation); onChanged(); }
      return true;
    } catch (err) {
      if (mounted.current) {
        await load();
        if (mounted.current) setError(errorMessage(err));
      }
      return false;
    } finally { sendingRef.current = false; if (mounted.current) setSending(false); }
  }
  const last = history?.messages.at(-1);
  const retryable = last?.role === "user" && (last.status === "failed" || (last.status === "pending" && !history?.conversation.generating));
  return <><header className="chat-thread-header"><div><span className="eyebrow">课次对话</span>{history ? <ChatTitleEditor conversation={history.conversation} disabled={sending || history.conversation.generating} onRenamed={(item) => { setHistory({ ...history, conversation: item }); onChanged(); }} /> : <h2>正在读取对话</h2>}</div>{history && <div className="chat-thread-actions"><Link className="button button-quiet" href={`/lessons/${history.conversation.lesson_id}/summary`}>查看本课纪要 ↗</Link><ChatDeleteButton conversation={history.conversation} disabled={sending || history.conversation.generating} onDeleted={onDeleted} /></div>}</header>
    {error && <div className="chat-thread-notice"><p role="alert">{error}</p><button className="button button-secondary" onClick={() => void load()}>重新加载</button></div>}
    <div className="chat-message-scroll"><div className="chat-message-column">{loading ? <p role="status">正在读取消息…</p> : history?.messages.length ? <ChatMessageList messages={history.messages} generating={history.conversation.generating} /> : !error && <div className="chat-empty-conversation"><h3>有什么想弄明白的？</h3><p>回答会依据本课次的文字记录与纪要，并附上原文时间点。</p></div>}{retryable && <button className="button button-secondary" disabled={sending} onClick={() => void send(last.content, last.request_id)}>重试这条问题</button>}<div ref={bottom} /></div></div>
    {history && <ChatComposer disabled={loading || history.conversation.generating} busy={sending} onSend={send} />}</>;
}
