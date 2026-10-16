"use client";
import { useState, type FormEvent } from "react";

export default function ChatComposer({ disabled, busy, onSend, scope, onStop, canStop, stopping }: { disabled: boolean; busy: boolean; onSend: (content: string) => Promise<boolean>; scope: "global" | "course" | "lesson"; onStop: () => void; canStop: boolean; stopping: boolean }) {
  const [draft, setDraft] = useState("");
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (disabled || busy || draft.trim().length < 2) return;
    if (await onSend(draft.trim())) setDraft("");
  }
  return <footer className="chat-composer-wrap"><form className="chat-composer" onSubmit={submit}><label className="sr-only" htmlFor="chat-question">{scope === "global" ? "向所有课程提问" : scope === "course" ? "向整门课程提问" : "向本课次提问"}</label><textarea id="chat-question" value={draft} maxLength={1000} rows={2} placeholder={scope === "global" ? "查询课程、知识点或错题，也可以根据薄弱点出题…" : scope === "course" ? "查询这门课的内容、知识点或错题，也可以根据薄弱点出题…" : "针对这节课提问，也可以接着追问…"} disabled={disabled || busy} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} /><div className="chat-composer-bottom"><span>Enter 发送 · Shift + Enter 换行</span>{canStop || stopping ? <button type="button" className="button button-secondary" disabled={stopping} onClick={onStop}>{stopping ? "正在停止…" : "■ 停止生成"}</button> : <button type="submit" className="button button-primary" disabled={disabled || busy || draft.trim().length < 2}>{busy ? "回答中…" : "发送 ↑"}</button>}</div></form><p>{scope === "global" ? "使用范围：你账号下的所有课程。" : scope === "course" ? "使用范围：当前课程，可查询课堂内容、知识点和错题，或生成练习。" : "检索范围：仅本课次的文字记录和纪要。"}重要内容请打开引用核对。</p></footer>;
}
