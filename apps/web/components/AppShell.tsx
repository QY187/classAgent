"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const libraryActive = pathname === "/" || pathname.startsWith("/courses") || pathname.startsWith("/lessons");
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">C</span>
          <span className="brand-copy"><span className="brand-name">ClassAgent</span><span className="brand-subtitle">课堂学习助手</span></span>
        </Link>
        <div className="nav-label">工作台</div>
        <nav className="nav">
          <Link className={`nav-item ${libraryActive ? "active" : ""}`} href="/"><span className="nav-icon">▦</span><span>课程库</span></Link>
          <button className="nav-item" disabled title="全局搜索，即将开放"><span className="nav-icon">⌕</span><span>全局搜索 · 即将开放</span></button>
          <button className="nav-item" disabled title="课程问答，即将开放"><span className="nav-icon">✦</span><span>课程问答 · 即将开放</span></button>
        </nav>
        <div className="sidebar-footer">先把课堂内容保存下来，再慢慢整理成自己的知识库。</div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div className="breadcrumb">我的学习空间</div>
          <div className="topbar-actions">
            <span className="status-text" style={{ color: "#7a8291", fontSize: 12 }}>本地预览版</span>
            <span className="user-chip"><span className="avatar">我</span><span className="status-text">我的资料库</span></span>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
