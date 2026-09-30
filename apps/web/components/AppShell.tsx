"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { request } from "../lib/api";
import { clearSession, getStoredUser, isAuthenticated, redirectToLogin, type AuthUser } from "../lib/auth";

type Course = { id: string; name: string };
type Lesson = { id: string; course_id: string; title: string };
type Breadcrumb = { pathname: string; courseId?: string; courseName?: string; lessonName?: string };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname === "/login";
  const [breadcrumb, setBreadcrumb] = useState<Breadcrumb>({ pathname: "" });
  const [user, setUser] = useState<AuthUser | null>(null);
  const libraryActive = pathname === "/" || pathname.startsWith("/courses") || pathname.startsWith("/lessons");
  const courseMatch = pathname.match(/^\/courses\/([^/]+)\/?$/);
  const lessonMatch = pathname.match(/^\/lessons\/([^/]+)\/?$/);

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
    request<AuthUser>("/auth/me")
      .then(setUser)
      .catch(() => {});
  }, [isLogin]);

  useEffect(() => {
    const controller = new AbortController();
    setBreadcrumb({ pathname });

    if (courseMatch) {
      request<Course[]>("/courses", { signal: controller.signal })
        .then((courses) => setBreadcrumb({ pathname, courseId: courseMatch[1], courseName: courses.find((course) => course.id === courseMatch[1])?.name }))
        .catch(() => {});
    } else if (lessonMatch) {
      request<Lesson>(`/lessons/${lessonMatch[1]}`, { signal: controller.signal })
        .then(async (lesson) => {
          if (controller.signal.aborted) return;
          setBreadcrumb({ pathname, courseId: lesson.course_id, lessonName: lesson.title });
          const courses = await request<Course[]>("/courses", { signal: controller.signal });
          if (!controller.signal.aborted) setBreadcrumb({ pathname, courseId: lesson.course_id, courseName: courses.find((course) => course.id === lesson.course_id)?.name, lessonName: lesson.title });
        })
        .catch(() => {});
    }

    return () => controller.abort();
  }, [pathname]);

  function logout() {
    clearSession();
    window.location.href = "/login";
  }

  const currentBreadcrumb: Breadcrumb = breadcrumb.pathname === pathname ? breadcrumb : { pathname };

  if (isLogin) return <>{children}</>;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">C</span>
          <span className="brand-copy"><span className="brand-name">ClassAgent</span><span className="brand-subtitle">课堂学习助手</span></span>
        </Link>
        <div className="nav-label">我的空间</div>
        <nav className="nav" aria-label="主导航">
          <Link className={`nav-item ${libraryActive ? "active" : ""}`} href="/"><span className="nav-icon">▦</span><span>课程库</span></Link>
        </nav>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <nav className="breadcrumb" aria-label="当前位置">
            {courseMatch || lessonMatch ? <Link className="breadcrumb-link" href="/">我的学习空间</Link> : <span className="breadcrumb-current" aria-current="page">我的学习空间</span>}
            {(courseMatch || (lessonMatch && currentBreadcrumb.courseId)) && <><span className="breadcrumb-separator" aria-hidden="true">/</span>{lessonMatch && currentBreadcrumb.courseId ? <Link className="breadcrumb-link" href={`/courses/${currentBreadcrumb.courseId}`}>{currentBreadcrumb.courseName || "我的课程"}</Link> : <span className="breadcrumb-current" aria-current="page">{currentBreadcrumb.courseName || "我的课程"}</span>}</>}
            {lessonMatch && <><span className="breadcrumb-separator" aria-hidden="true">/</span><span className="breadcrumb-current" aria-current="page">{currentBreadcrumb.lessonName || "我的课次"}</span></>}
          </nav>
          <div className="topbar-actions">
            <span className="status-text" style={{ color: "#7a8291", fontSize: 12 }}>本地预览版</span>
            {user && (
              <span className="user-chip">
                <span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>
                <span className="status-text">{user.username}</span>
                <button className="button button-quiet" style={{ fontSize: 12, padding: "4px 8px" }} type="button" onClick={logout}>退出</button>
              </span>
            )}
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
