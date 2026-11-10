"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiUrl, request } from "../lib/api";
import { clearSession, getRefreshToken, getStoredUser, isAuthenticated, redirectToLogin, type AuthUser } from "../lib/auth";
import SearchBox from "./SearchBox";
import SidebarAccount from "./SidebarAccount";
import SidebarIcon from "./SidebarIcon";
import SiteFooter from "./SiteFooter";

type Course = { id: string; name: string };
type LessonInfo = { course_id: string; title: string };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname === "/login";
  const [user, setUser] = useState<AuthUser | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [lessonInfo, setLessonInfo] = useState<LessonInfo | null>(null);
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const sidebarCollapsed = isMobile ? !mobileOpen : desktopCollapsed;
  useEffect(() => {
    let preference: string | null = null;
    try { preference = window.localStorage.getItem("classagent:sidebar-collapsed"); } catch {}
    setDesktopCollapsed(preference === "true");
    const media = window.matchMedia("(max-width: 640px)");
    const resize = () => { setIsMobile(media.matches); setMobileOpen(false); };
    resize();
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);
  useEffect(() => { setMobileOpen(false); }, [pathname]);
  useEffect(() => {
    if (!isMobile || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarRef.current?.querySelector<HTMLButtonElement>(".sidebar-mobile-close")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setMobileOpen(false); }
      if (event.key !== "Tab") return;
      const elements = [...(sidebarRef.current?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),[tabindex="0"]') || [])]
        .filter(element => element.getClientRects().length > 0);
      const first = elements[0], last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", keydown);
      toggleRef.current?.focus({ preventScroll: true });
    };
  }, [isMobile, mobileOpen]);
  function toggleSidebar() {
    if (isMobile) { setMobileOpen(open => !open); return; }
    const collapsed = !sidebarCollapsed;
    setDesktopCollapsed(collapsed);
    try { window.localStorage.setItem("classagent:sidebar-collapsed", String(collapsed)); } catch {}
  }
  const courseMatch = pathname.match(/^\/courses\/([^/]+)(?:\/.*)?$/);
  const lessonMatch = pathname.match(/^\/lessons\/([^/]+)(?:\/.*)?\/?$/);
  const activeCourseId = lessonMatch && lessonInfo ? lessonInfo.course_id : courseMatch?.[1];
  const pendingActive = pathname === "/pending-lessons";
  const libraryActive = pathname === "/" || pathname.startsWith("/courses") || pathname.startsWith("/lessons") || pendingActive;
  const reviewActive = pathname === "/review";
  const wrongBookActive = pathname === "/wrong-questions";
  const recycleActive = pathname === "/recycle-bin";
  const searchActive = pathname === "/search";
  const chatActive = pathname === "/chat";
  const settingsActive = pathname === "/settings";
  const quotasActive = pathname === "/quotas";
  const monitoringActive = pathname === "/monitoring";

  useEffect(() => {
    if (isLogin) {
      if (isAuthenticated()) window.location.href = "/";
      return;
    }
    if (!isAuthenticated()) {
      redirectToLogin();
      return;
    }
    setUser(getStoredUser());
    request<AuthUser>("/auth/me").then(setUser).catch(() => {});
    request<Course[]>("/courses").then(setCourses).catch(() => {});
  }, [isLogin]);

  useEffect(() => {
    if (isLogin) return;
    const refreshCourses = () => { request<Course[]>("/courses").then(setCourses).catch(() => {}); };
    window.addEventListener("classagent:courses-updated", refreshCourses);
    return () => window.removeEventListener("classagent:courses-updated", refreshCourses);
  }, [isLogin]);

  useEffect(() => {
    if (isLogin) return;
    const controller = new AbortController();
    if (lessonMatch) {
      request<{ course_id: string; title: string }>(`/lessons/${lessonMatch[1]}`, { signal: controller.signal })
        .then((lesson) => { if (!controller.signal.aborted) setLessonInfo(lesson); })
        .catch(() => {});
    } else {
      setLessonInfo(null);
    }
    return () => controller.abort();
  }, [pathname, isLogin]);

  async function logout() {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      fetch(`${apiUrl}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {});
    }
    clearSession();
    window.location.href = "/login";
  }

  if (isLogin) return <div className="public-shell">{children}<SiteFooter /></div>;

  const activeCourseName = activeCourseId ? courses.find((course) => course.id === activeCourseId)?.name : undefined;
  const lessonTitle = lessonMatch ? lessonInfo?.title : undefined;

  return (
    <div className={`app-shell${sidebarCollapsed ? " sidebar-is-collapsed" : ""}${isMobile && mobileOpen ? " mobile-navigation-open" : ""}`}>
      {isMobile && mobileOpen && <button type="button" className="sidebar-backdrop" tabIndex={-1} aria-label="关闭左侧导航遮罩" onClick={() => setMobileOpen(false)} />}
      <aside ref={sidebarRef} id="app-sidebar" className={`sidebar${sidebarCollapsed ? " sidebar-collapsed" : ""}`} aria-label="左侧导航" role={isMobile && mobileOpen ? "dialog" : undefined} aria-modal={isMobile && mobileOpen ? true : undefined} inert={isMobile && !mobileOpen ? true : undefined} onClick={(event) => { if (isMobile && (event.target as Element).closest("a[href]")) setMobileOpen(false); }}>
        {!sidebarCollapsed && <button type="button" className="sidebar-mobile-close" onClick={toggleSidebar} aria-label="关闭左侧导航" title="关闭左侧导航">×</button>}
        <Link href="/" className="brand" aria-label="ClassAgent 课程库" title="ClassAgent 课程库">
          <img className="brand-mark" src="/classagent-logo.svg" alt="" aria-hidden="true" />
          <span className="brand-copy"><span className="brand-name">ClassAgent</span><span className="brand-subtitle">课堂学习助手</span></span>
        </Link>
        <div className="nav-label">我的空间</div>
        <nav className="nav" aria-label="主导航">
          <Link className={`nav-item ${libraryActive && !activeCourseId ? "active" : ""}`} href="/" aria-label="课程库" title="课程库"><span className="nav-icon"><SidebarIcon name="library" /></span><span>课程库</span></Link>
          <Link className={`nav-item ${searchActive ? "active" : ""}`} href="/search" aria-label="全局搜索" title="全局搜索"><span className="nav-icon"><SidebarIcon name="search" /></span><span>全局搜索</span></Link>
          <Link className={`nav-item ${reviewActive ? "active" : ""}`} href="/review" aria-label="知识点清单" title="知识点清单"><span className="nav-icon"><SidebarIcon name="knowledge" /></span><span>知识点清单</span></Link>
          <Link className={`nav-item ${chatActive ? "active" : ""}`} href="/chat" aria-label="问答工作台" title="问答工作台"><span className="nav-icon"><SidebarIcon name="chat" /></span><span>问答工作台</span></Link>
          <Link className={`nav-item ${wrongBookActive ? "active" : ""}`} href="/wrong-questions" aria-label="错题本" title="错题本"><span className="nav-icon"><SidebarIcon name="notebook" /></span><span>错题本</span></Link>
          <Link className={`nav-item ${recycleActive ? "active" : ""}`} href="/recycle-bin" aria-label="回收站" title="回收站"><span className="nav-icon"><SidebarIcon name="trash" /></span><span>回收站</span></Link>
          <Link className={`nav-item ${quotasActive ? "active" : ""}`} href="/quotas" aria-label="Token 额度" title="Token 额度"><span className="nav-icon"><SidebarIcon name="quota" /></span><span>Token 额度</span></Link>
          {user?.role === "admin" && <Link className={`nav-item ${monitoringActive ? "active" : ""}`} href="/monitoring" aria-label="运行监控" title="运行监控"><span className="nav-icon"><SidebarIcon name="monitor" /></span><span>运行监控</span></Link>}
        </nav>
        <div className="side-section">
          <div className="nav-label">我的课程</div>
          <div className="side-course-list">
            {courses.length === 0 && <div className="side-course-empty">还没有课程</div>}
            {courses.slice(0, 8).map((course) => (
              <Link key={course.id} href={`/courses/${course.id}`} className={`side-course ${activeCourseId === course.id ? "active" : ""}`} title={course.name}>
                <span className="side-course-icon"><SidebarIcon name="folder" /></span>
                <span className="side-course-name">{course.name}</span>
              </Link>
            ))}
            {courses.length > 8 && <Link href="/" className="side-course-more">查看全部课程 →</Link>}
          </div>
        </div>
        <div className="side-footer">
          <SidebarAccount user={user} pathname={pathname} collapsed={sidebarCollapsed} onLogout={logout} />
        </div>
      </aside>
      <div className="main-area" inert={isMobile && mobileOpen ? true : undefined}>
        <header className="topbar">
          <button ref={toggleRef} type="button" className="sidebar-toggle" onClick={toggleSidebar} aria-controls="app-sidebar" aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "展开左侧导航" : "收起左侧导航"} title={sidebarCollapsed ? "展开左侧导航" : "收起左侧导航"}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /><path d={sidebarCollapsed ? "m13 9 3 3-3 3" : "m16 9-3 3 3 3"} /></svg></button>
          <nav className="breadcrumb" aria-label="当前位置">
            {courseMatch || lessonMatch || chatActive || searchActive || reviewActive || wrongBookActive || recycleActive || settingsActive || quotasActive || pendingActive || monitoringActive ? <Link className="breadcrumb-link" href="/">我的学习空间</Link> : <span className="breadcrumb-current" aria-current="page">我的学习空间</span>}
            {pendingActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">待处理课次</span></>}
            {chatActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">问答工作台</span></>}
            {recycleActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">回收站</span></>}
            {wrongBookActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">错题本</span></>}
            {searchActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">全局搜索</span></>}
            {reviewActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">知识点清单</span></>}
            {settingsActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">个人设置</span></>}
            {quotasActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">Token 额度</span></>}
            {monitoringActive && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">运行监控</span></>}
            {(courseMatch || (lessonMatch && lessonInfo)) && <><span className="breadcrumb-separator" aria-hidden="true">/</span>{lessonMatch && lessonInfo ? <Link className="breadcrumb-link" href={`/courses/${lessonInfo.course_id}`}>{activeCourseName || "我的课程"}</Link> : <span className="breadcrumb-current" aria-current="page">{activeCourseName || "我的课程"}</span>}</>}
            {lessonMatch && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">{lessonTitle || "我的课次"}</span></>}
            {lessonMatch && pathname.endsWith("/summary") && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">智能纪要</span></>}
            {lessonMatch && pathname.endsWith("/transcript") && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">文字记录</span></>}
            {lessonMatch && pathname.endsWith("/review") && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">复习卡片</span></>}
          </nav>
          <div className="topbar-actions">
            <SearchBox />
            <span className="status-text" style={{ color: "#7a8291", fontSize: 12 }}>本地预览版</span>
          </div>
        </header>
        {children}
        <SiteFooter />
      </div>
    </div>
  );
}
