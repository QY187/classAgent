"use client";
import { useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatArchiveButton({ conversation, onChanged, compact = false }: {
  conversation: Conversation; onChanged: (item: Conversation) => void; compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const label = conversation.is_archived ? "恢复对话" : "归档对话";
  async function toggle() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const item = await request<Conversation>(`/chat/conversations/${conversation.id}/archive`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_archived: !conversation.is_archived }),
      });
      onChanged(item);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <span className="chat-pin-control"><button type="button" className={compact ? "chat-list-pin" : "button button-quiet"} title={label} aria-label={`${label}：${conversation.title}`} disabled={busy || conversation.generating} onClick={toggle}>
    {compact ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{conversation.is_archived ? <path d="M5 10v11h14V10M3 10h5M16 10h5M12 15V3m-4 4 4-4 4 4" /> : <path d="M3 3h18v5H3zM5 8v13h14V8M9 12h6" />}</svg> : busy ? "处理中…" : label}
  </button>{error && <span className="chat-pin-error" role="alert">{error}</span>}</span>;
}
