"use client";
import { useCallback, useEffect, useState } from "react";
import type { Conversation } from "../../lib/chat";
import ChatLessonTree from "./ChatLessonTree";
import ChatConversationList from "./ChatConversationList";
import ChatThread from "./ChatThread";

export default function ChatWorkspace() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const loaded = useCallback((item: Conversation) => { setSelectedLessonId(item.lesson_id); setSelectedCourseId(item.course_id); }, []);
  const [revision, setRevision] = useState(0);
  const changed = useCallback(() => setRevision((value) => value + 1), []);
  const deleted = useCallback(() => { setSelectedId(null); window.history.replaceState(null, "", "/chat"); setRevision((value) => value + 1); }, []);
  useEffect(() => {
    const restore = () => {
      const params = new URLSearchParams(window.location.search);
      setSelectedId(params.get("conversation"));
      setSelectedLessonId(null);
      setSelectedCourseId(params.get("conversation") ? null : params.get("course"));
    };
    restore(); window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  function select(item: Conversation) {
    setSelectedId(item.id); setSelectedLessonId(item.lesson_id); setSelectedCourseId(item.course_id);
    window.history.pushState(null, "", `/chat?conversation=${encodeURIComponent(item.id)}`);
  }
  return <main className="chat-workspace"><ChatLessonTree selectedLessonId={selectedLessonId} selectedCourseId={selectedCourseId} onSelect={select} revision={revision}
    renderCourse={(course) => <ChatConversationList targetId={course.id} scope="course" selectedId={selectedId} onSelect={select} revision={revision} />}
    renderLesson={(lesson) => <ChatConversationList targetId={lesson.id} scope="lesson" selectedId={selectedId} onSelect={select} revision={revision} />} /><section className="chat-main">{selectedId ? <ChatThread key={selectedId} conversationId={selectedId} onLoaded={loaded} onChanged={changed} onDeleted={deleted} /> : <div className="chat-welcome"><span className="chat-welcome-icon">◌</span><h2>想聊整门课程，还是某一节课？</h2><p>展开左侧课程，可以新建课程对话；展开课次，可以新建课次对话。</p></div>}</section></main>;
}
