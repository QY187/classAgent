"use client";

import { useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatPinButton({ conversation, onChanged }: {
  conversation: Conversation; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const action = conversation.is_pinned ? "取消置顶" : "置顶对话";
  async function toggle() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await request<Conversation>(`/chat/conversations/${conversation.id}/pin`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_pinned: !conversation.is_pinned }),
      });
      onChanged();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <span className="chat-pin-control">
    <button type="button" className={`chat-list-pin${conversation.is_pinned ? " is-pinned" : ""}`} aria-label={`${action}：${conversation.title}`} aria-pressed={conversation.is_pinned} title={action} disabled={busy} onClick={toggle}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m16 3 5 5-4 2-3 5-2 1-4-4 1-2 5-3 2-4ZM3 21l7-7" /></svg>
    </button>
    {error && <span className="chat-pin-error" role="alert">{error}</span>}
  </span>;
}
