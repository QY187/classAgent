import type { ChatMessage } from "./chat";

export function chatRequestIdentity(last: ChatMessage | undefined, content: string, modelId: string,
  retryRequest?: string, newId: () => string = () => crypto.randomUUID()) {
  const previousModel = last?.model?.id || "default";
  if (retryRequest) {
    if (last?.role !== "user" || last.request_id !== retryRequest || last.content !== content) {
      throw new Error("这条问题之后已有新消息，请重新发送。");
    }
    return { requestId: retryRequest, modelId: previousModel };
  }
  const retry = last?.role === "user" && last.content === content
    && (last.status === "failed" || last.status === "pending") && previousModel === modelId;
  return { requestId: retry ? last.request_id : newId(), modelId };
}
