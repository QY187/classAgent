"use client";
import { useRef, useState } from "react";
import type { ChatCourse } from "../../lib/chat";
import { errorMessage, request } from "../../lib/api";

export default function ChatCoursePicker({ courses, onSelected }: { courses: ChatCourse[]; onSelected: (course: ChatCourse) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  function select(course: ChatCourse) { onSelected(course); dialog.current?.close(); }
  async function create() {
    if (busy || !name.trim()) return;
    setBusy(true); setError("");
    try {
      const course = await request<ChatCourse>("/courses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
      select(course); setName("");
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <><button type="button" className="chat-heading-action" aria-label="添加课程" title="添加课程" onClick={() => { setError(""); dialog.current?.showModal(); }}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v3"/><path d="M3 7v12a2 2 0 0 0 2 2h8M16 17h6m-3-3v6"/></svg></button>
    <dialog className="chat-course-picker panel" ref={dialog} aria-labelledby="chat-course-picker-title">
      <div className="panel-header"><h2 id="chat-course-picker-title">添加课程</h2><button className="button button-quiet" disabled={busy} onClick={() => dialog.current?.close()}>关闭</button></div>
      <div className="panel-body"><label className="field-label">选择已有课程<input className="field" type="search" placeholder="搜索已有课程" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="chat-course-options">{courses.filter((course) => course.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map((course) => <button key={course.id} disabled={busy} onClick={() => select(course)}>▱ {course.name}<span>进入课程 →</span></button>)}{!courses.some((course) => course.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && <p>没有匹配的课程</p>}</div>
        <form onSubmit={(event) => { event.preventDefault(); void create(); }}><label className="field-label">创建新课程<input className="field" placeholder="输入新课程名称" value={name} maxLength={200} required disabled={busy} onChange={(event) => setName(event.target.value)} /></label><button className="button button-primary" disabled={busy || !name.trim()}>{busy ? "创建中…" : "创建并进入课程"}</button></form>
        {error && <p className="notice" role="alert">{error}</p>}
      </div>
    </dialog></>;
}
