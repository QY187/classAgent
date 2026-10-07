"use client";
import { useEffect, useRef, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import type { Conversation } from "../../lib/chat";

export default function ChatDeleteButton({ conversation, disabled, onDeleted }: { conversation: Conversation; disabled: boolean; onDeleted: () => void }) {
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
  return <><button className="button button-quiet" aria-label="删除当前对话" disabled={disabled} onClick={() => { setError(""); setOpen(true); }}>删除对话</button><dialog className="modal chat-delete-dialog" ref={dialog} aria-labelledby="chat-delete-title" onCancel={(event) => { if (busy) event.preventDefault(); else setOpen(false); }} onClose={() => setOpen(false)}><h2 id="chat-delete-title">删除对话？</h2><p>「{conversation.title}」及其中全部问题、回答和依据记录将被删除，无法恢复。</p><p className="delete-impact">本课次的录音、文字记录和纪要仍然保留。</p>{error && <p role="alert" className="notice">{error}</p>}<div className="modal-actions"><button className="button button-secondary" autoFocus disabled={busy} onClick={() => setOpen(false)}>取消</button><button className="button button-danger" disabled={busy} onClick={remove}>{busy ? "删除中…" : "确认删除"}</button></div></dialog></>;
}
