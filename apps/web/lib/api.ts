import { clearSession, getToken, redirectToLogin } from "./auth";

export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { ...(options?.headers as Record<string, string> | undefined) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers,
    signal: options?.signal ?? AbortSignal.timeout(15000),
  });

  // 登录接口的 401 是“账号或密码错误”，不属于会话过期
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    clearSession();
    redirectToLogin();
    throw new Error("登录已过期，请重新登录");
  }

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    if (typeof detail === "string" && detail) throw new Error(detail);
    if (Array.isArray(detail) && detail.length > 0) throw new Error("请输入用户名和密码后再登录。");
    throw new Error("请求失败，请稍后重试。");
  }
  return response.json();
}

export function errorMessage(error: unknown): string {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")
    ? "连接失败，请检查网络和后端服务后重试。"
    : error instanceof Error ? error.message : "操作失败，请重试。";
}
