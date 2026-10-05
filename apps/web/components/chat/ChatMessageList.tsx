import Link from "next/link";
import type { ChatMessage } from "../../lib/chat";

function time(ms: number) { return `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`; }

export default function ChatMessageList({ messages, generating }: { messages: ChatMessage[]; generating: boolean }) {
  return <>{messages.map((message) => <article key={message.id} className={`chat-message ${message.role}`}><div className="chat-message-role">{message.role === "user" ? "你" : "课堂助手"}<time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div><div className="chat-message-content">{message.content}</div>
    {message.status === "failed" && <p className="chat-message-error">{message.error_message || "回答失败，请重试"}</p>}
    {message.status === "pending" && <p className="chat-message-status" role="status">{generating ? "正在查找课堂依据并整理回答…" : "上次回答已中断，可以重试。"}</p>}
    {message.citations.length > 0 && <details className="chat-evidence"><summary>查看回答依据 · {message.citations.length} 条引用</summary><div>{message.citations.map((citation) => <Link className="chat-citation" key={citation.id} href={`/lessons/${citation.lesson_id}/transcript?t=${citation.start_ms}`}><span className="chat-citation-number">[{citation.id}]</span><span><strong>{citation.lesson_title} · {time(citation.start_ms)}</strong><p>{citation.snippet}</p></span><span aria-hidden="true">↗</span></Link>)}</div></details>}
  </article>)}</>;
}
