"use client";
import { useEffect, useState, type ReactNode } from "react";
import { errorMessage, request } from "../../lib/api";
import ChatArchivePanel from "./ChatArchivePanel";
import ChatCoursePicker from "./ChatCoursePicker";
import type { ChatCourse, ChatLesson, ChatSearchResult, Conversation } from "../../lib/chat";

export default function ChatLessonTree({ renderCourse, selectedLessonId, selectedCourseId, onSelect, revision, renderGlobal, onCourseSelected, onRestored }: {
  onRestored: (item: Conversation) => void;
  renderGlobal: (heading: (action: ReactNode) => ReactNode) => ReactNode; onCourseSelected: (course: ChatCourse) => void;
  renderCourse: (course: ChatCourse, heading: (action: ReactNode) => ReactNode, collapsed: boolean) => ReactNode;
  selectedLessonId: string | null; selectedCourseId: string | null; onSelect: (item: Conversation) => void; revision: number;
}) {
  const [lessons, setLessons] = useState<ChatLesson[]>([]);
  const [courseItems, setCourseItems] = useState<ChatCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [retry, setRetry] = useState(0);

  const [collapsedCourses, setCollapsedCourses] = useState<Record<string, boolean>>({});
  const [hits, setHits] = useState<ChatSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

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
  }, [retry, revision]);
  const needle = query.trim().toLocaleLowerCase();
  const courses = courseItems.filter((course) => !needle || course.name.toLocaleLowerCase().includes(needle));
  return <aside className="chat-tree" aria-label="课程与对话"><header className="chat-tree-header"><h1>问答工作台</h1><p>主对话跨课程，课程内聚焦学习</p><div className="chat-tree-search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></svg><input className="field" type="search" maxLength={200} aria-label="搜索课程或对话" placeholder="搜索课程或对话" value={query} onChange={(event) => setQuery(event.target.value)} /></div></header><div className="chat-tree-scroll">
    <section className="chat-global-section">{renderGlobal((action) => <div className="chat-section-heading"><h2>主对话<span>全部课程</span></h2>{action}</div>)}</section><div className="chat-courses-label"><h2>课程</h2><ChatCoursePicker courses={courseItems} onSelected={onCourseSelected} /></div>
    {query.trim() && <section className="chat-course-group"><h2>匹配的对话{hits.length === 100 ? " · 最近 100 条" : ""}</h2>{searching ? <p className="chat-tree-hint" role="status">正在搜索…</p> : searchError ? <p className="chat-tree-hint" role="alert">{searchError}</p> : hits.length ? hits.map((item) => <button className="chat-search-hit" key={item.id} onClick={() => onSelect(item)}><strong>{item.title}</strong><span>{item.scope === "global" ? "主对话 · 全部课程" : `${item.course_name} / ${item.lesson_title || "整门课程"}`}</span></button>) : <p className="chat-tree-hint">没有匹配的对话</p>}</section>}
    {loading && !courseItems.length ? <p className="chat-tree-hint" role="status">正在读取课程…</p> : error ? <div className="chat-tree-hint"><p role="alert">{error}</p><button className="button button-secondary" onClick={() => setRetry((value) => value + 1)}>重新加载</button></div> : !courses.length ? <p className="chat-tree-hint">{courseItems.length ? "没有匹配的课程" : "还没有课程，可以点击“添加课程”创建。"}</p> : courses.map((course) => <section className="chat-course-group" key={course.id}>
      {renderCourse(course, (action) => <div className="chat-course-heading"><h2><button type="button" className="chat-course-toggle" aria-current={selectedCourseId === course.id ? "true" : undefined} aria-expanded={!collapsedCourses[course.id]} onClick={() => setCollapsedCourses((current) => ({ ...current, [course.id]: !current[course.id] }))}><span className="chat-course-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5.5C9 3.7 5.5 3.4 3 4v15c2.5-.6 6-.3 9 1.5 3-1.8 6.5-2.1 9-1.5V4c-2.5-.6-6-.3-9 1.5Z" /><path d="M12 5.5v15" /></svg></span><span className="chat-tree-chevron" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="m6 4 4 4-4 4" /></svg></span><span className="chat-course-title">{course.name}</span></button></h2>{action}</div>, !!collapsedCourses[course.id])}
    </section>)}
    <ChatArchivePanel revision={revision} onSelect={onSelect} onRestored={onRestored} />
  </div></aside>;
}
