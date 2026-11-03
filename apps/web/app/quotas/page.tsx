"use client";

import { useEffect, useState } from "react";
import TokenQuotaSettings from "../../components/settings/TokenQuotaSettings";
import { errorMessage, request } from "../../lib/api";
import type { AuthUser } from "../../lib/auth";

export default function TokenQuotasPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    request<AuthUser>("/auth/me", { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setUser(result); })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); });
    return () => controller.abort();
  }, []);

  return (
    <main className="content token-quota-page">
      <div className="settings-heading token-quota-page-heading">
        <span className="eyebrow">AI 用量</span>
        <h1>Token 额度</h1>
        <p>掌握 AI 使用情况，让每一次调用都有迹可循。</p>
      </div>
      {error && <div className="notice login-notice settings-message" role="alert">{error}</div>}
      {user ? <TokenQuotaSettings isAdmin={user.role === "admin"} /> : !error && <p role="status">正在加载额度页面…</p>}
    </main>
  );
}
