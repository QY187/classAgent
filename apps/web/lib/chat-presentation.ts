import type { ChatCitation } from "./chat";
import { materialHref } from "./materials";
export function citationTarget(messageId: string, id: number) { return `chat-source-${encodeURIComponent(messageId)}-${id}`; }
export function citationTime(ms: number) {
  const seconds = Math.floor(Math.max(0, ms) / 1000), minutes = Math.floor(seconds / 60);
  return `${minutes >= 60 ? `${String(Math.floor(minutes / 60)).padStart(2, "0")}:` : ""}${String(minutes % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
export function citationTitle(item: ChatCitation) {
  const course = item.course_name ? `${item.course_name} → ` : "";
  return item.source_type === "material" ? `${course}${item.filename} · ${item.locator_label} · 课件` :
    `${course}${item.lesson_title} · ${citationTime(item.start_ms)}${item.end_ms != null && item.end_ms > item.start_ms ? `–${citationTime(item.end_ms)}` : ""} · 录音`;
}
export function citationHref(item: ChatCitation): string | null {
  if (item.source_status === "unavailable") return null;
  return item.source_type === "material" ? materialHref(item) : `/lessons/${encodeURIComponent(item.lesson_id)}/transcript?t=${item.start_ms}`;
}
export function answerWithSources(content: string, citations: ChatCitation[], origin: string) {
  if (!citations.length) return content;
  return content + "\n\n回答依据\n" + citations.map(item => {
    const href = citationHref(item);
    return `[${item.id}] ${citationTitle(item)}\n${item.snippet}\n${href ? new URL(href, origin).href : "来源已删除或当前不可访问"}${item.source_status === "changed" ? "\n来源版本已变化，请重新核对" : ""}`;
  }).join("\n\n");
}
