"use client";
import { useCallback, useEffect, useState } from "react";
import type { Conversation } from "../../lib/chat";
import ChatLessonTree from "./ChatLessonTree";
import ChatConversationList from "./ChatConversationList";
import ChatThread from "./ChatThread";

export default function ChatWorkspace() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const loaded = useCallback((item: Conversation) => setSelectedLessonId(item.lesson_id), []);
  const [revision, setRevision] = useState(0);
  const changed = useCallback(() => setRevision((value) => value + 1), []);
  const deleted = useCallback(() => { setSelectedId(null); window.history.replaceState(null, "", "/chat"); setRevision((value) => value + 1); }, []);
  useEffect(() => {
    const restore = () => setSelectedId(new URLSearchParams(window.location.search).get("conversation"));
    restore(); window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  function select(item: Conversation) {
    setSelectedId(item.id); setSelectedLessonId(item.lesson_id);
    window.history.pushState(null, "", `/chat?conversation=${encodeURIComponent(item.id)}`);
  }
  return <main className="chat-workspace"><ChatLessonTree selectedLessonId={selectedLessonId} renderLesson={(lesson) => <ChatConversationList lesson={lesson} selectedId={selectedId} onSelect={select} revision={revision} />} /><section className="chat-main">{selectedId ? <ChatThread key={selectedId} conversationId={selectedId} onLoaded={loaded} onChanged={changed} onDeleted={deleted} /> : <div className="chat-welcome"><span className="chat-welcome-icon">◌</span><h2>从一节课开始对话</h2><p>在左侧展开课次，查看或新建对话。</p></div>}</section></main>;
}
