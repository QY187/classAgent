export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    signal: options?.signal ?? AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "请求失败，请稍后重试。");
  }
  return response.json();
}

export function errorMessage(error: unknown): string {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")
    ? "连接失败，请检查网络和后端服务后重试。"
    : error instanceof Error ? error.message : "操作失败，请重试。";
}
