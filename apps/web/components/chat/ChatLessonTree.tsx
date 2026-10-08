"use client";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, request } from "../../lib/api";
import type { ChatCourse, ChatLesson, ChatSearchResult, Conversation } from "../../lib/chat";

export default function ChatLessonTree({ renderLesson, renderCourse, selectedLessonId, selectedCourseId, onSelect, revision }: {
  renderLesson: (lesson: ChatLesson) => ReactNode; renderCourse: (course: ChatCourse) => ReactNode;
  selectedLessonId: string | null; selectedCourseId: string | null; onSelect: (item: Conversation) => void; revision: number;
}) {
  const [lessons, setLessons] = useState<ChatLesson[]>([]);
  const [courseItems, setCourseItems] = useState<ChatCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [retry, setRetry] = useState(0);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [collapsedCourses, setCollapsedCourses] = useState<Record<string, boolean>>({});
  const [hits, setHits] = useState<ChatSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  useEffect(() => { if (selectedLessonId) setExpanded((current) => ({ ...current, [selectedLessonId]: true })); }, [selectedLessonId]);
  useEffect(() => {
    const courseId = selectedCourseId || lessons.find((lesson) => lesson.id === selectedLessonId)?.course_id;
    if (courseId) setCollapsedCourses((current) => current[courseId] ? { ...current, [courseId]: false } : current);
  }, [selectedCourseId, selectedLessonId, lessons]);
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
    Promise.all([request<ChatLesson[]>("/chat/lessons", { signal: controller.signal }), request<ChatCourse[]>("/courses", { signal: controller.signal })])
      .then(([lessonItems, courses]) => { if (!controller.signal.aborted) { setLessons(lessonItems); setCourseItems(courses); } })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [retry]);
  const needle = query.trim().toLocaleLowerCase();
  const visible = lessons.filter((lesson) => `${lesson.title} ${lesson.course_name}`.toLocaleLowerCase().includes(needle));
  const courses = courseItems.filter((course) => !needle || course.name.toLocaleLowerCase().includes(needle) || visible.some((lesson) => lesson.course_id === course.id));
  return <aside className="chat-tree" aria-label="课程课次与对话"><header className="chat-tree-header"><h1>问答工作台</h1><p>聊整门课程，也可以细聊一节课</p><input className="field" type="search" maxLength={200} aria-label="搜索课程、课次或对话" placeholder="搜索课程、课次或对话" value={query} onChange={(event) => setQuery(event.target.value)} /></header><div className="chat-tree-scroll">
    {query.trim() && <section className="chat-course-group"><h2>匹配的对话{hits.length === 100 ? " · 最近 100 条" : ""}</h2>{searching ? <p className="chat-tree-hint" role="status">正在搜索…</p> : searchError ? <p className="chat-tree-hint" role="alert">{searchError}</p> : hits.length ? hits.map((item) => <button className="chat-search-hit" key={item.id} onClick={() => onSelect(item)}><strong>{item.title}</strong><span>{item.course_name} / {item.lesson_title || "整门课程"}</span></button>) : <p className="chat-tree-hint">没有匹配的对话</p>}</section>}
    {loading ? <p className="chat-tree-hint" role="status">正在读取课程…</p> : error ? <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-secondary" onClick={() => setRetry((value) => value + 1)}>重新加载</button></div> : !courses.length ? <p className="chat-tree-hint">{courseItems.length ? "没有匹配的课程或课次" : "先在课程库创建课程，再开始对话。"}</p> : courses.map((course) => <section className="chat-course-group" key={course.id}>
      <h2 className="chat-course-heading"><button type="button" className="chat-course-toggle" aria-expanded={!collapsedCourses[course.id]} onClick={() => setCollapsedCourses((current) => ({ ...current, [course.id]: !current[course.id] }))}><span className="chat-course-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5.5C9 3.7 5.5 3.4 3 4v15c2.5-.6 6-.3 9 1.5 3-1.8 6.5-2.1 9-1.5V4c-2.5-.6-6-.3-9 1.5Z" /><path d="M12 5.5v15" /></svg></span><span className="chat-course-title">{course.name}</span><span className="chat-course-label">课程</span><span className="chat-tree-chevron" aria-hidden="true">{collapsedCourses[course.id] ? "›" : "⌄"}</span></button></h2>
      {!collapsedCourses[course.id] && <div><div className="chat-course-conversations"><span className="chat-scope-caption">整门课程</span>{renderCourse(course)}</div><span className="chat-scope-caption chat-lesson-caption">课次</span>{visible.filter((lesson) => lesson.course_id === course.id).map((lesson) => <details className="chat-lesson" key={lesson.id} open={!!query || !!expanded[lesson.id]} onToggle={(event) => { const open = event.currentTarget.open; setExpanded((current) => current[lesson.id] === open ? current : { ...current, [lesson.id]: open }); }}><summary><span>{lesson.title}</span><span className="chat-tree-chevron" aria-hidden="true">⌄</span></summary>{(expanded[lesson.id] || query) && renderLesson(lesson)}</details>)}{!lessons.some((lesson) => lesson.course_id === course.id) && <p className="chat-tree-hint">这门课程还没有课次</p>}</div>}
    </section>)}
  </div></aside>;
}
