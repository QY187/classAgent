"use client";
import { useState, type FormEvent } from "react";

export default function ChatComposer({ disabled, busy, onSend }: { disabled: boolean; busy: boolean; onSend: (content: string) => Promise<boolean> }) {
  const [draft, setDraft] = useState("");
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (disabled || busy || draft.trim().length < 2) return;
    if (await onSend(draft.trim())) setDraft("");
  }
  return <footer className="chat-composer-wrap"><form className="chat-composer" onSubmit={submit}><label className="sr-only" htmlFor="chat-question">向本课次提问</label><textarea id="chat-question" value={draft} maxLength={1000} rows={3} placeholder="针对这节课提问，也可以接着追问…" disabled={disabled || busy} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} /><div className="chat-composer-bottom"><span>Enter 发送 · Shift + Enter 换行</span><button type="submit" className="button button-primary" disabled={disabled || busy || draft.trim().length < 2}>{busy ? "回答中…" : "发送 ↑"}</button></div></form><p>回答依据本课次资料生成，重要内容请打开引用核对。</p></footer>;
}
