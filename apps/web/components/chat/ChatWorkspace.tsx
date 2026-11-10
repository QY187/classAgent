"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatCourse, Conversation } from "../../lib/chat";
import ChatLessonTree from "./ChatLessonTree";
import ChatConversationList from "./ChatConversationList";
import ChatThread from "./ChatThread";

export default function ChatWorkspace() {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationRef = useRef<HTMLDivElement>(null);
  const navigationToggle = useRef<HTMLButtonElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const viewport = window.visualViewport;
    const media = window.matchMedia("(max-width: 640px)");
    const resize = () => {
      if (media.matches) {
        workspaceRef.current?.style.setProperty("--chat-viewport-height", `${viewport?.height ?? window.innerHeight}px`);
      } else workspaceRef.current?.style.removeProperty("--chat-viewport-height");
    };
    const breakpointChanged = () => { setNavigationOpen(false); resize(); };
    resize();
    media.addEventListener("change", breakpointChanged);
    viewport?.addEventListener("resize", resize);
    window.addEventListener("resize", resize);
    return () => { media.removeEventListener("change", breakpointChanged); viewport?.removeEventListener("resize", resize); window.removeEventListener("resize", resize); };
  }, []);
  useEffect(() => {
    if (!navigationOpen) return;
    const outside = (event: PointerEvent) => {
      if (!navigationRef.current?.contains(event.target as Node) && !navigationToggle.current?.contains(event.target as Node)) setNavigationOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setNavigationOpen(false); navigationToggle.current?.focus(); } };
    const focusOutside = (event: FocusEvent) => {
      if (!navigationRef.current?.contains(event.target as Node) && !navigationToggle.current?.contains(event.target as Node)) setNavigationOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    document.addEventListener("focusin", focusOutside);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      document.removeEventListener("focusin", focusOutside);
    };
  }, [navigationOpen]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const loaded = useCallback((item: Conversation) => { setSelectedLessonId(item.lesson_id); setSelectedCourseId(item.course_id); }, []);
  const [threadRevision, setThreadRevision] = useState(0);
  const [revision, setRevision] = useState(0);
  const changed = useCallback(() => setRevision((value) => value + 1), []);
  const deleted = useCallback(() => { setSelectedId(null); window.history.replaceState(null, "", "/chat"); setRevision((value) => value + 1); }, []);
  useEffect(() => {
    const restore = () => {
      setNavigationOpen(false);
      const params = new URLSearchParams(window.location.search);
      setSelectedId(params.get("conversation"));
      setSelectedLessonId(null);
      setSelectedCourseId(params.get("conversation") ? null : params.get("course"));
    };
    restore(); window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  function listDeleted(id: string) {
    if (id === selectedId) deleted();
    else changed();
  }
  function courseSelected(course: ChatCourse) {
    setNavigationOpen(false);
    setSelectedId(null); setSelectedLessonId(null); setSelectedCourseId(course.id); changed();
    window.history.pushState(null, "", `/chat?course=${encodeURIComponent(course.id)}`);
  }
  function select(item: Conversation) {
    setNavigationOpen(false);
    setSelectedId(item.id); setSelectedLessonId(item.lesson_id); setSelectedCourseId(item.course_id);
    window.history.pushState(null, "", `/chat?conversation=${encodeURIComponent(item.id)}`);
  }
  return <main ref={workspaceRef} className={`chat-workspace${navigationOpen ? " navigation-is-open" : ""}`}>
    <button ref={navigationToggle} type="button" className="chat-mobile-navigation" aria-label="课程与对话" title="课程与对话" aria-expanded={navigationOpen} aria-controls="chat-navigation" onClick={() => setNavigationOpen(value => !value)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 6h16M4 12h10M4 18h13" /></svg></button>
    <div ref={navigationRef} id="chat-navigation" className="chat-navigation"><ChatLessonTree selectedLessonId={selectedLessonId} selectedCourseId={selectedCourseId} onSelect={select} revision={revision} onCourseSelected={courseSelected} onRestored={(item) => { if (item.id === selectedId) setThreadRevision(v => v + 1); changed(); }}
    renderGlobal={(heading, collapsed) => <ChatConversationList targetId="" scope="global" selectedId={selectedId} onSelect={select} revision={revision} onDeleted={listDeleted} onPinned={changed} onArchived={listDeleted} renderHeading={heading} collapsed={collapsed} />}
    renderCourse={(course, heading, collapsed) => <ChatConversationList targetId={course.id} scope="course" selectedId={selectedId} onSelect={select} revision={revision} onDeleted={listDeleted} onPinned={changed} onArchived={listDeleted} renderHeading={heading} collapsed={collapsed} />} /></div><section className="chat-main">{!selectedId && <header className="chat-mobile-welcome-header"><strong>问答工作台</strong><small>课程与历史对话按需展开</small></header>}{selectedId ? <ChatThread key={`${selectedId}:${threadRevision}`} conversationId={selectedId} onLoaded={loaded} onChanged={changed} onDeleted={deleted} /> : <div className="chat-welcome"><span className="chat-welcome-icon">◌</span><h2>{selectedCourseId ? "开始这门课程的对话" : "今天想了解什么？"}</h2><p>{selectedCourseId ? "点击课程列表中的新建图标，开始这门课程的对话。" : "主对话可以查询所有课程；选择课程后，可专注这门课程的课堂内容。"}</p>{!selectedCourseId && <ChatConversationList targetId="" scope="global" createOnly selectedId={null} onSelect={select} revision={revision} />}</div>}</section></main>;
}
