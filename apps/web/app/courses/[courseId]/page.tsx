"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import CourseQa from "../../../components/CourseQa";
import CourseMaterials from "../../../components/CourseMaterials";

type Course = { id: string; name: string; semester?: string | null };
type Lesson = { id: string; title: string; lesson_date?: string | null; status: string; created_at: string };
const statusLabel: Record<string, string> = { created: "待录音", audio_only: "仅保存音频", queued: "排队中", transcribing: "转写中", completed: "已有文字记录", failed: "处理失败" };

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingLessonId, setUploadingLessonId] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<{ lessonId: string; text: string; failed: boolean } | null>(null);
  const [materialsRefreshKey, setMaterialsRefreshKey] = useState(0);
  const [expandedLessonId, setExpandedLessonId] = useState<string | null>(null);
  const [editingCourse, setEditingCourse] = useState(false);
  const [editingLesson, setEditingLesson] = useState<Lesson | null>(null);
  const [editName, setEditName] = useState("");
  const [editDate, setEditDate] = useState("");
  const [editError, setEditError] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const [deletingCourse, setDeletingCourse] = useState(false);
  const [deletingLesson, setDeletingLesson] = useState<Lesson | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

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

  function openCourseEdit() {
    if (!course) return;
    setEditName(course.name); setEditDate(course.semester || ""); setEditError(""); setEditingCourse(true);
  }

  function openLessonEdit(lesson: Lesson) {
    setEditName(lesson.title); setEditDate(lesson.lesson_date || ""); setEditError(""); setEditingLesson(lesson);
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editName.trim() || editSaving) return;
    setEditSaving(true); setEditError("");
    try {
      if (editingCourse) {
        const updated = await request<Course>(`/courses/${courseId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: editName.trim(), semester: editDate.trim() || null }) });
        setCourse(updated); setEditingCourse(false);
        window.dispatchEvent(new Event("classagent:courses-updated"));
      } else if (editingLesson) {
        const updated = await request<Lesson>(`/lessons/${editingLesson.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: editName.trim(), lesson_date: editDate || null }) });
        setLessons((current) => current.map((item) => item.id === updated.id ? updated : item)); setEditingLesson(null);
      }
    } catch (error) { setEditError(errorMessage(error)); }
    finally { setEditSaving(false); }
  }

  async function confirmDelete() {
    if (deleteBusy || (!deletingCourse && !deletingLesson)) return;
    setDeleteBusy(true); setDeleteError("");
    try {
      if (deletingCourse) {
        await request<void>(`/courses/${courseId}`, { method: "DELETE" });
        window.dispatchEvent(new Event("classagent:courses-updated"));
        router.push("/");
      } else if (deletingLesson) {
        await request<void>(`/lessons/${deletingLesson.id}`, { method: "DELETE" });
        setLessons((current) => current.filter((item) => item.id !== deletingLesson.id));
        setExpandedLessonId((current) => current === deletingLesson.id ? null : current);
        setDeletingLesson(null);
      }
    } catch (error) { setDeleteError(errorMessage(error)); }
    finally { setDeleteBusy(false); }
  }

  async function uploadMaterials(event: ChangeEvent<HTMLInputElement>, lesson: Lesson) {
    const input = event.target;
    const files = Array.from(input.files || []);
    if (!files.length || uploadingLessonId) return;
    setUploadingLessonId(lesson.id);
    const failures: string[] = [];
    let uploaded = 0;
    try {
      for (const [index, file] of files.entries()) {
        setUploadStatus({ lessonId: lesson.id, text: `正在上传 ${index + 1}/${files.length}：${file.name}`, failed: false });
        if (file.size === 0 || file.size > 25 * 1024 * 1024) {
          failures.push(`${file.name}：文件须为非空且不超过 25 MB`);
          continue;
        }
        try {
          const body = new FormData();
          body.append("file", file);
          body.append("lesson_id", lesson.id);
          await request(`/courses/${courseId}/materials`, { method: "POST", body, signal: AbortSignal.timeout(120000) });
          uploaded += 1;
        } catch (error) { failures.push(`${file.name}：${errorMessage(error)}`); }
      }
      if (uploaded) {
        setMaterialsRefreshKey((key) => key + 1);
        setExpandedLessonId(lesson.id);
      }
      setUploadStatus({ lessonId: lesson.id, text: `已上传 ${uploaded} 份资料${failures.length ? `，失败 ${failures.length} 份：${failures.join("；")}` : ""}`, failed: failures.length > 0 });
    } finally {
      input.value = "";
      setUploadingLessonId(null);
    }
  }

  if (loading) return <main className="content"><p role="status">正在加载课程…</p></main>;
  if (!course) return <main className="content"><div className="empty-state"><div className="empty-icon">▱</div><strong>{message || "课程不存在"}</strong><p>这门课程可能已被删除，回到课程库看看其他课程。</p><Link className="button button-secondary" href="/">返回课程库</Link></div></main>;

  return <main className="content">
    <section className="page-hero course-management-hero">
      <span className="page-hero-avatar">{course.name.slice(0, 1)}</span>
      <div className="page-hero-copy">
        <div className="eyebrow">课程空间</div>
        <h1>{course.name}</h1>
        <p>{course.semester || "未设置学期"} · {lessons.length} 节课 · 持续整理这门课的每一次学习</p>
      </div>
      <div className="page-hero-actions"><button className="button button-secondary" onClick={openCourseEdit}>编辑课程</button><button className="button material-delete-button" onClick={() => { setDeleteError(""); setDeletingCourse(true); }}>删除课程</button><button className="button button-primary" onClick={() => setShowModal(true)}>＋ 新建课次</button></div>
    </section>
    {message && <div className="notice" style={{ marginBottom: 16 }}>{message}</div>}
    <CourseQa courseId={courseId} />
    <section className="panel quiz-entry-panel"><div><span className="eyebrow">课后练习</span><h2>课堂小测</h2><p>从这门课的文字记录生成有课堂依据的题目，先核对再作答。</p></div><Link className="button button-secondary" href={`/courses/${courseId}/quizzes`}>进入小测 →</Link></section>
    <section className="panel">
      <div className="panel-header"><h2>课次记录</h2><span>{lessons.length} 节课</span></div>
      <div className="panel-body">
        {lessons.length === 0 ? <div className="empty-state"><div className="empty-icon">◷</div><strong>还没有课次</strong><p>创建课次后上传录音，开始建立这门课的资料库。</p><button className="button button-primary" onClick={() => setShowModal(true)}>创建第一节课</button></div> : <div className="lesson-list">{lessons.map((lesson, index) => <div className="lesson-row" key={lesson.id}>
          <Link className="lesson-row-link" href={`/lessons/${lesson.id}`}><span className="lesson-index">{String(index + 1).padStart(2, "0")}</span><span className="lesson-main"><span className="lesson-title">{lesson.title}</span><span className="lesson-date">{lesson.lesson_date || "未设置日期"}</span></span></Link>
          <div className="lesson-row-actions">
            <button type="button" className="button button-secondary" onClick={() => openLessonEdit(lesson)} aria-label={`编辑${lesson.title}`}>编辑</button>
            <button type="button" className="button material-delete-button" onClick={() => { setDeleteError(""); setDeletingLesson(lesson); }} aria-label={`删除${lesson.title}`}>删除</button>
            <label className={`button button-secondary lesson-upload${uploadingLessonId ? " is-disabled" : ""}`} role="button" tabIndex={uploadingLessonId ? -1 : 0} aria-label={`为${lesson.title}上传资料`} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.currentTarget.click(); } }}><input className="upload-input" type="file" multiple accept=".pdf,.ppt,.pptx,.doc,.docx,.png,.jpg,.jpeg,.webp,.txt,.md" onChange={(event) => uploadMaterials(event, lesson)} disabled={Boolean(uploadingLessonId)} />{uploadingLessonId === lesson.id ? "上传中…" : "＋ 上传资料"}</label>
            <button type="button" className="button button-secondary lesson-view-materials" aria-expanded={expandedLessonId === lesson.id} aria-controls={`lesson-materials-${lesson.id}`} onClick={() => setExpandedLessonId((current) => current === lesson.id ? null : lesson.id)}>{expandedLessonId === lesson.id ? "收起资料" : "查看资料"}</button>
            <span className={`pill pill-${lesson.status}`}>{statusLabel[lesson.status] || lesson.status}</span>
            <Link className="lesson-go" href={`/lessons/${lesson.id}`} aria-label={`进入${lesson.title}`}>→</Link>
          </div>
          {uploadStatus?.lessonId === lesson.id && <div className={`lesson-upload-status${uploadStatus.failed ? " is-error" : ""}`} role="status">{uploadStatus.text}</div>}
          {expandedLessonId === lesson.id && <CourseMaterials courseId={courseId} lessonId={lesson.id} refreshKey={materialsRefreshKey} />}
        </div>)}</div>}
      </div>
    </section>
    {showModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowModal(false); }}><form className="modal" role="dialog" aria-modal="true" aria-label="创建资料" onKeyDown={(event) => { if (event.key === "Escape" && !saving) setShowModal(false); }} onSubmit={createLesson}><h2>新建课次</h2>{message && <p role="alert" className="notice">{message}</p>}<div className="form-grid"><label className="field-label">课次标题<input className="field" required maxLength={200} autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：第 1 讲：二叉树" /></label><label className="field-label">上课日期<input className="field" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label></div><div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setShowModal(false)}>取消</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? "创建中…" : "创建课次"}</button></div></form></div>}
    {(editingCourse || editingLesson) && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !editSaving) { setEditingCourse(false); setEditingLesson(null); } }}><form className="modal" role="dialog" aria-modal="true" aria-label={editingCourse ? "编辑课程" : "编辑课次"} onKeyDown={(event) => { if (event.key === "Escape" && !editSaving) { setEditingCourse(false); setEditingLesson(null); } }} onSubmit={saveEdit}><h2>{editingCourse ? "编辑课程" : "编辑课次"}</h2>{editError && <p role="alert" className="notice">{editError}</p>}<div className="form-grid"><label className="field-label">{editingCourse ? "课程名称" : "课次标题"}<input className="field" required maxLength={200} autoFocus value={editName} onChange={(event) => setEditName(event.target.value)} /></label><label className="field-label">{editingCourse ? "学期（可选）" : "上课日期"}<input className="field" type={editingCourse ? "text" : "date"} maxLength={editingCourse ? 100 : undefined} value={editDate} onChange={(event) => setEditDate(event.target.value)} /></label></div><div className="modal-actions"><button type="button" className="button button-secondary" disabled={editSaving} onClick={() => { setEditingCourse(false); setEditingLesson(null); }}>取消</button><button className="button button-primary" type="submit" disabled={editSaving}>{editSaving ? "保存中…" : "保存修改"}</button></div></form></div>}
    {(deletingCourse || deletingLesson) && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleteBusy) { setDeletingCourse(false); setDeletingLesson(null); } }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-course-lesson-title" onKeyDown={(event) => { if (event.key === "Escape" && !deleteBusy) { setDeletingCourse(false); setDeletingLesson(null); } }}><h2 id="delete-course-lesson-title">{deletingCourse ? "删除课程" : "删除课次"}</h2><p>确定删除「<strong className="material-delete-filename">{deletingCourse ? course.name : deletingLesson?.title}</strong>」吗？</p><p className="delete-impact">{deletingCourse ? `这门课程的 ${lessons.length} 节课，以及所有录音、文字记录、纪要、知识点和上传资料都会被删除。` : "本节的录音、文字记录、纪要、知识点和上传资料都会被删除。"}删除后无法恢复。</p>{deleteError && <p className="notice" role="alert">删除失败：{deleteError}</p>}<div className="modal-actions"><button type="button" className="button button-secondary" autoFocus disabled={deleteBusy} onClick={() => { setDeletingCourse(false); setDeletingLesson(null); }}>取消</button><button type="button" className="button button-danger" disabled={deleteBusy} onClick={confirmDelete}>{deleteBusy ? "正在删除…" : "确认删除"}</button></div></div></div>}
  </main>;
}
