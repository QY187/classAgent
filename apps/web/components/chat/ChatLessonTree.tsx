"use client";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, request } from "../../lib/api";
import type { ChatLesson } from "../../lib/chat";

export default function ChatLessonTree({ renderLesson, selectedLessonId }: { renderLesson?: (lesson: ChatLesson) => ReactNode; selectedLessonId?: string | null }) {
  const [lessons, setLessons] = useState<ChatLesson[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [retry, setRetry] = useState(0);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
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
  return <aside className="chat-tree" aria-label="课次与对话"><header className="chat-tree-header"><h1>问答工作台</h1><p>每节课，都可以接着聊</p><input className="field" type="search" aria-label="搜索课程或课次" placeholder="搜索课程或课次" value={query} onChange={(event) => setQuery(event.target.value)} /></header><div className="chat-tree-scroll">
    {loading ? <p className="chat-tree-hint" role="status">正在读取课次…</p> : error ? <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-secondary" onClick={() => setRetry((value) => value + 1)}>重新加载</button></div> : !visible.length ? <p className="chat-tree-hint">{lessons.length ? "没有匹配的课次" : "先在课程库创建课次，再开始对话。"}</p> : courses.map((courseId) => <section className="chat-course-group" key={courseId}><h2>{visible.find((lesson) => lesson.course_id === courseId)?.course_name}</h2>{visible.filter((lesson) => lesson.course_id === courseId).map((lesson) => <details className="chat-lesson" key={lesson.id} open={!!query || expanded[lesson.id] || lesson.id === selectedLessonId} onToggle={(event) => { const open = event.currentTarget.open; setExpanded((current) => current[lesson.id] === open ? current : { ...current, [lesson.id]: open }); }}><summary><span>{lesson.title}</span><span className="chat-tree-chevron" aria-hidden="true">⌄</span></summary>{(expanded[lesson.id] || query || lesson.id === selectedLessonId) && renderLesson?.(lesson)}</details>)}</section>)}
  </div></aside>;
}
