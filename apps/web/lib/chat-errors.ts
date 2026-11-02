import { errorMessage } from "./api";

export function chatFailureMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return "等待回答超时，暂时无法确认服务器是否仍在处理，请重新加载查看结果。";
  }
  if (error instanceof TypeError) {
    return "浏览器与服务器连接失败，暂时无法确认处理结果。请检查网络后重新加载。";
  }
  return errorMessage(error);
}
