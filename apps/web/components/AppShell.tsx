"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { request } from "../lib/api";
import { clearSession, getStoredUser, isAuthenticated, redirectToLogin, type AuthUser } from "../lib/auth";

type Course = { id: string; name: string };
type LessonInfo = { course_id: string; title: string };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname === "/login";
  const [user, setUser] = useState<AuthUser | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [lessonInfo, setLessonInfo] = useState<LessonInfo | null>(null);
  const courseMatch = pathname.match(/^\/courses\/([^/]+)\/?$/);
  const lessonMatch = pathname.match(/^\/lessons\/([^/]+)\/?$/);
  const activeCourseId = lessonMatch && lessonInfo ? lessonInfo.course_id : courseMatch?.[1];
  const libraryActive = pathname === "/" || pathname.startsWith("/courses") || pathname.startsWith("/lessons");

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

  function logout() {
    clearSession();
    window.location.href = "/login";
  }

  if (isLogin) return <>{children}</>;

  const activeCourseName = activeCourseId ? courses.find((course) => course.id === activeCourseId)?.name : undefined;
  const lessonTitle = lessonMatch ? lessonInfo?.title : undefined;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">C</span>
          <span className="brand-copy"><span className="brand-name">ClassAgent</span><span className="brand-subtitle">课堂学习助手</span></span>
        </Link>
        <div className="nav-label">我的空间</div>
        <nav className="nav" aria-label="主导航">
          <Link className={`nav-item ${libraryActive && !activeCourseId ? "active" : ""}`} href="/"><span className="nav-icon">▦</span><span>课程库</span></Link>
        </nav>
        <div className="side-section">
          <div className="nav-label">我的课程</div>
          <div className="side-course-list">
            {courses.length === 0 && <div className="side-course-empty">还没有课程</div>}
            {courses.slice(0, 8).map((course) => (
              <Link key={course.id} href={`/courses/${course.id}`} className={`side-course ${activeCourseId === course.id ? "active" : ""}`}>
                <span className="side-course-dot" aria-hidden="true" />
                <span className="side-course-name">{course.name}</span>
              </Link>
            ))}
            {courses.length > 8 && <Link href="/" className="side-course-more">查看全部课程 →</Link>}
          </div>
        </div>
        <div className="side-footer">
          {user && <div className="side-user"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span><span className="side-user-name">{user.username}</span></div>}
          <button className="button button-secondary side-logout" type="button" onClick={logout}>退出登录</button>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <nav className="breadcrumb" aria-label="当前位置">
            {courseMatch || lessonMatch ? <Link className="breadcrumb-link" href="/">我的学习空间</Link> : <span className="breadcrumb-current" aria-current="page">我的学习空间</span>}
            {(courseMatch || (lessonMatch && lessonInfo)) && <><span className="breadcrumb-separator" aria-hidden="true">/</span>{lessonMatch && lessonInfo ? <Link className="breadcrumb-link" href={`/courses/${lessonInfo.course_id}`}>{activeCourseName || "我的课程"}</Link> : <span className="breadcrumb-current" aria-current="page">{activeCourseName || "我的课程"}</span>}</>}
            {lessonMatch && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">{lessonTitle || "我的课次"}</span></>}
          </nav>
          <div className="topbar-actions">
            <span className="status-text" style={{ color: "#7a8291", fontSize: 12 }}>本地预览版</span>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
