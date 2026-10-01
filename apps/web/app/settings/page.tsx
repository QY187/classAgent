"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import { clearSession, getStoredUser, type AuthUser } from "../../lib/auth";
import UserAvatar, { avatarUpdatedEvent } from "../../components/UserAvatar";

const maxAvatarSize = 2 * 1024 * 1024;

export default function SettingsPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const avatarInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setUser(getStoredUser());
    request<AuthUser>("/auth/me").then(setUser).catch((err) => setError(errorMessage(err)));
  }, []);

  async function uploadAvatar(file: File | undefined) {
    if (!file || uploadingAvatar) return;
    setError("");
    setNotice("");
    if (file.size > maxAvatarSize) {
      setError("头像不能超过 2 MB");
      return;
    }
    setUploadingAvatar(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const updated = await request<AuthUser>("/auth/avatar", { method: "POST", body: form });
      setUser(updated);
      window.dispatchEvent(new Event(avatarUpdatedEvent));
      setNotice("头像已更新");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUploadingAvatar(false);
      if (avatarInput.current) avatarInput.current.value = "";
    }
  }

  async function savePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingPassword) return;
    setError("");
    setNotice("");
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSavingPassword(true);
    try {
      await request("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      clearSession();
      window.location.href = "/login?password_changed=1";
    } catch (err) {
      setError(errorMessage(err));
      setSavingPassword(false);
    }
  }

  return (
    <main className="content settings-page">
      <div className="settings-heading"><span className="eyebrow">我的账号</span><h1>个人设置</h1><p>管理你的头像和登录密码。</p></div>
      {error && <div className="notice login-notice settings-message" role="alert">{error}</div>}
      {notice && <div className="notice login-success settings-message" role="status">{notice}</div>}

      <section className="settings-card settings-profile" aria-labelledby="settings-profile-title">
        <div className="settings-section-heading"><div><span className="settings-kicker">账号资料</span><h2 id="settings-profile-title">头像与用户名</h2></div></div>
        <div className="settings-profile-content">
          <UserAvatar username={user?.username ?? "?"} hasAvatar={user?.has_avatar} className="settings-profile-avatar" />
          <div className="settings-profile-info">
            <strong>{user?.username ?? "加载中…"}</strong>
            <span>用户名</span>
            <p>上传一张喜欢的头像，页面中的账号头像会同步更新。</p>
          </div>
          <div className="settings-upload-action">
            <input ref={avatarInput} className="settings-file-input" type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择头像图片" onChange={(event) => uploadAvatar(event.target.files?.[0])} />
            <button className="button button-secondary" type="button" disabled={uploadingAvatar} onClick={() => avatarInput.current?.click()}>{uploadingAvatar ? "上传中…" : "上传头像"}</button>
            <span>PNG、JPG 或 WebP，最多 2 MB</span>
          </div>
        </div>
      </section>

      <section className="settings-card settings-security" aria-labelledby="settings-password-title">
        <div className="settings-section-heading"><div><span className="settings-kicker">账号安全</span><h2 id="settings-password-title">修改密码</h2><p>定期更新密码，保护你的课程资料。</p></div></div>
        <form onSubmit={savePassword}>
          <div className="settings-password-fields">
            <label className="field-label settings-current-password">当前密码<input className="field" type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
            <label className="field-label">新密码<input className="field" type="password" autoComplete="new-password" required minLength={6} maxLength={200} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="至少 6 位" /></label>
            <label className="field-label">确认新密码<input className="field" type="password" autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label>
          </div>
          <div className="settings-password-footer"><p>保存后需要使用新密码重新登录。</p><button className="button button-primary" type="submit" disabled={savingPassword}>{savingPassword ? "保存中…" : "保存新密码"}</button></div>
        </form>
      </section>
    </main>
  );
}
