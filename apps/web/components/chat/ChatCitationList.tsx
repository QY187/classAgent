import Link from "next/link";
import type { ChatCitation } from "../../lib/chat";
import { materialHref } from "../../lib/materials";

function time(ms: number) { return `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`; }

export default function ChatCitationList({ citations }: { citations: ChatCitation[] }) {
  if (!citations.length) return null;
  return <details className="chat-evidence"><summary>查看回答依据 · {citations.length} 条引用</summary><div>{citations.map((citation) => {
    const material = citation.source_type === "material";
    const title = material ? `${citation.filename} · ${citation.locator_label} · 课件` : `${citation.lesson_title} · ${time(citation.start_ms)} · 录音`;
    const content = <><span className="chat-citation-number">[{citation.id}]</span><span><strong>{title}</strong><p>{citation.snippet}</p>{material && citation.source_status !== "current" && <p role="status">{citation.source_status === "unavailable" ? "来源已删除或当前不可访问" : "来源版本已变化，请重新提问核对"}</p>}</span></>;
    return material && citation.source_status === "unavailable" ? <div className="chat-citation" key={citation.id}>{content}</div> : <Link className="chat-citation" key={citation.id} href={material ? materialHref(citation) : `/lessons/${citation.lesson_id}/transcript?t=${citation.start_ms}`}>{content}<span aria-hidden="true">↗</span></Link>;
  })}</div></details>;
}
