"use client";

import { FormEvent, useEffect, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import { setSession } from "../../lib/auth";

type LoginResult = { access_token: string; refresh_token: string; token_type: string };
type MeResult = { username: string; role: string };

export default function LoginPage() {
  const registrationEnabled = process.env.NEXT_PUBLIC_ALLOW_REGISTRATION !== "false";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const [usernameChanged, setUsernameChanged] = useState(false);

  useEffect(() => {
    setPasswordChanged(new URLSearchParams(window.location.search).get("password_changed") === "1");
    setUsernameChanged(new URLSearchParams(window.location.search).get("username_changed") === "1");
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      if (mode === "register") {
        await request("/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
      }
      const login = await request<LoginResult>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const me = await request<MeResult>("/auth/me", {
        headers: { Authorization: `Bearer ${login.access_token}` },
      });
      setSession(login.access_token, login.refresh_token, me);
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
        <h1>{mode === "login" ? "登录到你的资料库" : "创建新账号"}</h1>
        <p className="login-sub">{mode === "login" ? "使用你的账号继续。" : "注册后即可建立自己的课程资料库。"}</p>
        {passwordChanged && <div className="notice login-success" role="status">密码已更新，请使用新密码登录。</div>}
        {usernameChanged && <div className="notice login-success" role="status">用户名已更新，请使用新用户名登录。</div>}
        {error && <div className="notice login-notice">{error}</div>}
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="field-label">用户名
            <input className="field" required autoFocus value={username} onChange={(event) => setUsername(event.target.value)} placeholder="用户名" autoComplete="username" />
          </label>
          <label className="field-label">密码
            <input className="field" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "至少 6 位" : "请输入密码"} autoComplete={mode === "register" ? "new-password" : "current-password"} />
          </label>
          <button className="button button-primary" type="submit" disabled={loading}>{loading ? (mode === "login" ? "登录中…" : "注册中…") : (mode === "login" ? "登录" : "注册并登录")}</button>
        </form>
        {registrationEnabled && <button className="login-switch" type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
          {mode === "login" ? "没有账号？注册一个" : "已有账号？返回登录"}
        </button>}
      </div>
    </div>
  );
}
