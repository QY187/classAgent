"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { AuthUser } from "../lib/auth";
import SidebarIcon from "./SidebarIcon";
import UserAvatar from "./UserAvatar";

export default function SidebarAccount({ user, pathname, collapsed, onLogout }: {
  user: AuthUser | null; pathname: string; collapsed: boolean; onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { setOpen(false); }, [pathname, collapsed]);
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keyboard);
    };
  }, [open]);
  const username = user?.username || "我的账户";
  return <div className="side-account" ref={container} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }}>
    <button ref={trigger} className={`side-account-trigger${open ? " is-open" : ""}`} type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="sidebar-account-menu" aria-label={`${username}，账户菜单`} title={`${username} · 账户菜单`}>
      <UserAvatar username={username} hasAvatar={user?.has_avatar} />
      <span className="side-account-copy"><span className="side-account-name">{username}</span><span className="side-account-caption">个人账户</span></span>
      <span className="side-account-more"><SidebarIcon name="more" /></span>
    </button>
    {open && <nav id="sidebar-account-menu" className="side-account-menu" aria-label="账户菜单">
      <div className="side-account-menu-label">账户</div>
      <Link href="/settings" className={`side-account-action${pathname === "/settings" ? " active" : ""}`} onClick={() => setOpen(false)}><SidebarIcon name="settings" /><span>个人设置</span></Link>
      <div className="side-account-menu-divider" />
      <button type="button" className="side-account-action" onClick={onLogout}><SidebarIcon name="logout" /><span>退出登录</span></button>
    </nav>}
  </div>;
}
