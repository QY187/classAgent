import Link from "next/link";
import type { ChatCitation } from "../../lib/chat";
import { citationHref, citationTarget, citationTitle } from "../../lib/chat-presentation";
export default function ChatCitationList({ citations, messageId = "citation" }: { citations: ChatCitation[]; messageId?: string }) {
  if (!citations.length) return null;
  return <details className="chat-evidence"><summary>查看回答依据 · {citations.length} 条引用</summary><div>{citations.map(citation => {
    const href = citationHref(citation);
    const content = <><span className="chat-citation-number">[{citation.id}]</span><span className="chat-citation-copy"><strong>{citationTitle(citation)}</strong><p>{citation.snippet}</p>{citation.source_status === "unavailable" && <p role="status">来源已删除或当前不可访问</p>}{citation.source_status === "changed" && <p role="status">来源版本已变化，请重新提问核对</p>}</span></>;
    return <div key={citation.id} id={citationTarget(messageId, citation.id)} className="chat-citation-target" tabIndex={-1}>{href ? <Link className="chat-citation" href={href}>{content}<span aria-hidden="true">↗</span></Link> : <div className="chat-citation">{content}</div>}</div>;
  })}</div></details>;
}
