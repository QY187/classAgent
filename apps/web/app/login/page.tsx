"use client";

import { FormEvent, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import { setSession } from "../../lib/auth";

type LoginResult = { access_token: string; token_type: string };
type MeResult = { username: string; role: string };

export default function LoginPage() {
  const [username, setUsername] = useState("root");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const login = await request<LoginResult>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const me = await request<MeResult>("/auth/me", {
        headers: { Authorization: `Bearer ${login.access_token}` },
      });
      setSession(login.access_token, me);
      window.location.href = "/";
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark">C</span>
          <span className="brand-copy"><span className="brand-name">ClassAgent</span><span className="brand-subtitle">课堂学习助手</span></span>
        </div>
        <h1>登录到你的资料库</h1>
        <p className="login-sub">使用管理员账号继续。</p>
        {error && <div className="notice login-notice">{error}</div>}
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="field-label">用户名
            <input className="field" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} placeholder="root" autoComplete="username" />
          </label>
          <label className="field-label">密码
            <input className="field" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入密码" autoComplete="current-password" />
          </label>
          <button className="button button-primary" type="submit" disabled={loading}>{loading ? "登录中…" : "登录"}</button>
        </form>
      </div>
    </div>
  );
}
