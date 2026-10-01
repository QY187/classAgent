"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import CourseQa from "../../../components/CourseQa";

type Course = { id: string; name: string; semester?: string | null };
type Lesson = { id: string; title: string; lesson_date?: string | null; status: string; created_at: string };
const statusLabel: Record<string, string> = { created: "待录音", audio_only: "仅保存音频", queued: "排队中", transcribing: "转写中", completed: "已有文字记录", failed: "处理失败" };

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Course | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
    const [courses, lessons] = await Promise.all([request<Course[]>("/courses"), request<Lesson[]>(`/courses/${courseId}/lessons`)]);
    setCourse(courses.find((item) => item.id === courseId) || null);
    setLessons(lessons);
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setLoading(false); }
  }
  useEffect(() => { if (courseId) load(); }, [courseId]);

  async function createLesson(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    if (saving) return;
    setSaving(true); setMessage("");
    try {
    const lesson = await request<Lesson>(`/courses/${courseId}/lessons`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim(), lesson_date: date || null }) });
    setLessons((items) => [lesson, ...items]);
    setTitle(""); setDate(""); setShowModal(false);
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setSaving(false); }
  }

  if (loading) return <main className="content"><p role="status">正在加载课程…</p></main>;
  if (!course) return <main className="content"><div className="empty-state"><div className="empty-icon">▱</div><strong>{message || "课程不存在"}</strong><p>这门课程可能已被删除，回到课程库看看其他课程。</p><Link className="button button-secondary" href="/">返回课程库</Link></div></main>;

  return <main className="content">
    <section className="page-hero">
      <span className="page-hero-avatar">{course.name.slice(0, 1)}</span>
      <div className="page-hero-copy">
        <div className="eyebrow">课程空间</div>
        <h1>{course.name}</h1>
        <p>{course.semester || "未设置学期"} · {lessons.length} 节课 · 持续整理这门课的每一次学习</p>
      </div>
      <div className="page-hero-actions"><button className="button button-primary" onClick={() => setShowModal(true)}>＋ 新建课次</button></div>
    </section>
    {message && <div className="notice" style={{ marginBottom: 16 }}>{message}</div>}
    <CourseQa courseId={courseId} />
    <section className="panel">
      <div className="panel-header"><h2>课次记录</h2><span>{lessons.length} 节课</span></div>
      <div className="panel-body">
        {lessons.length === 0 ? <div className="empty-state"><div className="empty-icon">◷</div><strong>还没有课次</strong><p>创建课次后上传录音，开始建立这门课的资料库。</p><button className="button button-primary" onClick={() => setShowModal(true)}>创建第一节课</button></div> : <div className="lesson-list">{lessons.map((lesson, index) => <Link className="lesson-row" href={`/lessons/${lesson.id}`} key={lesson.id}><span className="lesson-index">{String(index + 1).padStart(2, "0")}</span><span className="lesson-main"><span className="lesson-title">{lesson.title}</span><span className="lesson-date">{lesson.lesson_date || "未设置日期"}</span></span><span className={`pill pill-${lesson.status}`}>{statusLabel[lesson.status] || lesson.status}</span><span className="lesson-go" aria-hidden="true">→</span></Link>)}</div>}
      </div>
    </section>
    {showModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowModal(false); }}><form className="modal" role="dialog" aria-modal="true" aria-label="创建资料" onKeyDown={(event) => { if (event.key === "Escape" && !saving) setShowModal(false); }} onSubmit={createLesson}><h2>新建课次</h2>{message && <p role="alert" className="notice">{message}</p>}<div className="form-grid"><label className="field-label">课次标题<input className="field" required maxLength={200} autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：第 1 讲：二叉树" /></label><label className="field-label">上课日期<input className="field" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label></div><div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setShowModal(false)}>取消</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? "创建中…" : "创建课次"}</button></div></form></div>}
  </main>;
}
