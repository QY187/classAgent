"use client";
import { useEffect, useId, useRef, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatDeleteButton({ conversation, disabled, onDeleted, compact = false }: { conversation: Conversation; disabled: boolean; onDeleted: () => void; compact?: boolean }) {
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  async function remove() {
    if (busy) return;
    setBusy(true); setError("");
    try { await request(`/chat/conversations/${conversation.id}`, { method: "DELETE" }); setOpen(false); onDeleted(); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <><button type="button" className={compact ? "chat-list-delete" : "button button-quiet"} aria-label={compact ? `删除对话：${conversation.title}` : "删除当前对话"} title={compact ? "删除对话" : undefined} disabled={disabled} onClick={() => { setError(""); setOpen(true); }}>{compact ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></svg> : "删除对话"}</button><dialog className="modal chat-delete-dialog" ref={dialog} aria-labelledby={titleId} onCancel={(event) => { if (busy) event.preventDefault(); else setOpen(false); }} onClose={() => setOpen(false)}><h2 id={titleId}>删除对话？</h2><p>「{conversation.title}」及其中全部问题、回答和依据记录将被删除，无法恢复。</p><p className="delete-impact">课程、课次及其录音、文字记录和纪要仍然保留。</p>{error && <p role="alert" className="notice">{error}</p>}<div className="modal-actions"><button className="button button-secondary" autoFocus disabled={busy} onClick={() => setOpen(false)}>取消</button><button className="button button-danger" disabled={busy} onClick={remove}>{busy ? "删除中…" : "确认删除"}</button></div></dialog></>;
}
