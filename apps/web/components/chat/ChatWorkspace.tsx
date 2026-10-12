"use client";
import { useCallback, useEffect, useState } from "react";
import type { ChatCourse, Conversation } from "../../lib/chat";
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
  function courseSelected(course: ChatCourse) {
    setSelectedId(null); setSelectedLessonId(null); setSelectedCourseId(course.id); changed();
    window.history.pushState(null, "", `/chat?course=${encodeURIComponent(course.id)}`);
  }
  function select(item: Conversation) {
    setSelectedId(item.id); setSelectedLessonId(item.lesson_id); setSelectedCourseId(item.course_id);
    window.history.pushState(null, "", `/chat?conversation=${encodeURIComponent(item.id)}`);
  }
  return <main className="chat-workspace"><ChatLessonTree selectedLessonId={selectedLessonId} selectedCourseId={selectedCourseId} onSelect={select} revision={revision} onCourseSelected={courseSelected}
    renderGlobal={() => <ChatConversationList targetId="" scope="global" selectedId={selectedId} onSelect={select} revision={revision} />}
    renderCourse={(course) => <ChatConversationList targetId={course.id} scope="course" selectedId={selectedId} onSelect={select} revision={revision} />} /><section className="chat-main">{selectedId ? <ChatThread key={selectedId} conversationId={selectedId} onLoaded={loaded} onChanged={changed} onDeleted={deleted} /> : <div className="chat-welcome"><span className="chat-welcome-icon">◌</span><h2>{selectedCourseId ? "开始这门课程的对话" : "今天想了解什么？"}</h2><p>{selectedCourseId ? "在左侧课程下新建对话，围绕整门课程提问。" : "主对话可以查询所有课程；选择课程后，可专注这门课程的课堂内容。"}</p>{!selectedCourseId && <ChatConversationList targetId="" scope="global" createOnly selectedId={null} onSelect={select} revision={revision} />}</div>}</section></main>;
}
