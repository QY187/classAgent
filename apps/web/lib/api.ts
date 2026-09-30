import { clearSession, getRefreshToken, getToken, redirectToLogin, setTokens } from "./auth";

export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let refreshing: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  try {
    const response = await fetch(`${apiUrl}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (!data?.access_token) return null;
    setTokens(data.access_token as string, (data.refresh_token as string) ?? refreshToken);
    return data.access_token as string;
  } catch {
    return null;
  }
}

async function fetchWithToken(path: string, options: RequestInit | undefined, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { ...(options?.headers as Record<string, string> | undefined) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${apiUrl}${path}`, {
    ...options,
    headers,
    signal: options?.signal ?? AbortSignal.timeout(15000),
  });
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response = await fetchWithToken(path, options, getToken());

  // 登录/刷新接口的 401 是“凭证无效”，不属于会话过期
  const isAuthPath = path.startsWith("/auth/login") || path.startsWith("/auth/refresh") || path.startsWith("/auth/register");
  if (response.status === 401 && !isAuthPath) {
    refreshing ??= refreshAccessToken();
    const newToken = await refreshing;
    refreshing = null;
    if (newToken) {
      response = await fetchWithToken(path, options, newToken);
    } else {
      clearSession();
      redirectToLogin();
      throw new Error("登录已过期，请重新登录");
    }
  }

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    if (typeof detail === "string" && detail) throw new Error(detail);
    if (Array.isArray(detail) && detail.length > 0) throw new Error("请检查输入内容后重试。");
    throw new Error("请求失败，请稍后重试。");
  }
  return response.json();
}

export function errorMessage(error: unknown): string {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")
    ? "连接失败，请检查网络和后端服务后重试。"
    : error instanceof Error ? error.message : "操作失败，请重试。";
}
