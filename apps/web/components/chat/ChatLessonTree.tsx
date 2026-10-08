"use client";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, request } from "../../lib/api";
import type { ChatLesson, ChatSearchResult, Conversation } from "../../lib/chat";

export default function ChatLessonTree({ renderLesson, selectedLessonId, onSelect, revision }: { renderLesson?: (lesson: ChatLesson) => ReactNode; selectedLessonId?: string | null; onSelect: (item: Conversation) => void; revision: number }) {
  const [lessons, setLessons] = useState<ChatLesson[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [retry, setRetry] = useState(0);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [hits, setHits] = useState<ChatSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  useEffect(() => { if (selectedLessonId) setExpanded((current) => ({ ...current, [selectedLessonId]: true })); }, [selectedLessonId]);
  useEffect(() => {
    if (!query.trim()) { setHits([]); setSearching(false); setSearchError(""); return; }
    const controller = new AbortController(); setSearching(true); setSearchError(""); setHits([]);
    const timer = window.setTimeout(() => {
      request<ChatSearchResult[]>(`/chat/search?query=${encodeURIComponent(query.trim())}`, { signal: controller.signal })
        .then((result) => { if (!controller.signal.aborted) setHits(result); })
        .catch((err) => { if (!controller.signal.aborted) setSearchError(errorMessage(err)); })
        .finally(() => { if (!controller.signal.aborted) setSearching(false); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, revision]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    request<ChatLesson[]>("/chat/lessons", { signal: controller.signal }).then(setLessons)
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [retry]);
  const needle = query.trim().toLocaleLowerCase();
  const visible = lessons.filter((lesson) => `${lesson.title} ${lesson.course_name}`.toLocaleLowerCase().includes(needle));
  const courses = [...new Set(visible.map((lesson) => lesson.course_id))];
  return <aside className="chat-tree" aria-label="课次与对话"><header className="chat-tree-header"><h1>问答工作台</h1><p>每节课，都可以接着聊</p><input className="field" type="search" maxLength={200} aria-label="搜索课程、课次或对话" placeholder="搜索课程、课次或对话" value={query} onChange={(event) => setQuery(event.target.value)} /></header><div className="chat-tree-scroll">
    {query.trim() && <section className="chat-course-group"><h2>匹配的对话{hits.length === 100 ? " · 最近 100 条" : ""}</h2>{searching ? <p className="chat-tree-hint" role="status">正在搜索…</p> : searchError ? <p className="chat-tree-hint" role="alert">{searchError}</p> : hits.length ? hits.map((item) => <button className="chat-search-hit" key={item.id} onClick={() => onSelect(item)}><strong>{item.title}</strong><span>{item.course_name} / {item.lesson_title}</span></button>) : <p className="chat-tree-hint">没有匹配的对话</p>}</section>}
    {loading ? <p className="chat-tree-hint" role="status">正在读取课次…</p> : error ? <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-secondary" onClick={() => setRetry((value) => value + 1)}>重新加载</button></div> : !visible.length ? <p className="chat-tree-hint">{lessons.length ? "没有匹配的课次" : "先在课程库创建课次，再开始对话。"}</p> : courses.map((courseId) => <section className="chat-course-group" key={courseId}><h2>{visible.find((lesson) => lesson.course_id === courseId)?.course_name}</h2>{visible.filter((lesson) => lesson.course_id === courseId).map((lesson) => <details className="chat-lesson" key={lesson.id} open={!!query || !!expanded[lesson.id]} onToggle={(event) => { const open = event.currentTarget.open; setExpanded((current) => current[lesson.id] === open ? current : { ...current, [lesson.id]: open }); }}><summary><span>{lesson.title}</span><span className="chat-tree-chevron" aria-hidden="true">⌄</span></summary>{(expanded[lesson.id] || query) && renderLesson?.(lesson)}</details>)}</section>)}
  </div></aside>;
}
