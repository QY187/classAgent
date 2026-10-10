import { authorizedResponse } from "./api";
import type { ChatHistory, ChatCitation } from "./chat";

export type AnswerPreview = { answer: string; citations: ChatCitation[] };

export async function streamAnswer(conversationId: string, content: string, requestId: string,
  onPreview: (preview: AnswerPreview) => void, options?: { signal?: AbortSignal; onReady?: () => void }): Promise<ChatHistory> {
  const response = await authorizedResponse(`/chat/conversations/${conversationId}/ask/stream`, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ content, request_id: requestId }),
    signal: options?.signal,
  });
  if (!response.body) throw new Error("浏览器无法读取流式回答，请重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const lines = block.split("\n");
        const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const payload = JSON.parse(data);
        if (event === "status" && payload.ready === true) options?.onReady?.();
        if (event === "answer") onPreview(payload as AnswerPreview);
        if (event === "error") throw new Error(payload.detail || "回答失败，请重试。");
        if (event === "done") return payload as ChatHistory;
      }
      if (done) throw new Error("回答连接已中断，可重新加载查看结果或重试。");
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
