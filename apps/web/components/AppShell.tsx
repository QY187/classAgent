"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { request } from "../lib/api";

type Course = { id: string; name: string };
type Lesson = { id: string; course_id: string; title: string };
type Breadcrumb = { pathname: string; courseId?: string; courseName?: string; lessonName?: string };

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [breadcrumb, setBreadcrumb] = useState<Breadcrumb>({ pathname: "" });
  const libraryActive = pathname === "/" || pathname.startsWith("/courses") || pathname.startsWith("/lessons");
  const courseMatch = pathname.match(/^\/courses\/([^/]+)\/?$/);
  const lessonMatch = pathname.match(/^\/lessons\/([^/]+)\/?$/);

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

  const currentBreadcrumb: Breadcrumb = breadcrumb.pathname === pathname ? breadcrumb : { pathname };
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
            <span className="user-chip"><span className="avatar">我</span><span className="status-text">我的资料库</span></span>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
