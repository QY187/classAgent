"use client";
import { useState, type FormEvent } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatTitleEditor({ conversation, disabled, onRenamed }: { conversation: Conversation; disabled: boolean; onRenamed: (item: Conversation) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault(); if (busy || !draft.trim()) return;
    setBusy(true); setError("");
    try { onRenamed(await request<Conversation>(`/chat/conversations/${conversation.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: draft.trim() }) })); setEditing(false); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <div className="chat-title-editor">{editing ? <form onSubmit={save}><input className="field" autoFocus aria-label="对话标题" maxLength={200} value={draft} disabled={busy} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape" && !busy) setEditing(false); }} /><button className="button button-quiet" disabled={busy || !draft.trim()}>{busy ? "保存中" : "保存"}</button><button type="button" className="button button-quiet" disabled={busy} onClick={() => setEditing(false)}>取消</button></form> : <div><h2>{conversation.title}</h2><button className="button button-quiet" aria-label="修改对话标题" disabled={disabled} onClick={() => { setDraft(conversation.title); setError(""); setEditing(true); }}>✎</button></div>}{error && <p role="alert">{error}</p>}</div>;
}
