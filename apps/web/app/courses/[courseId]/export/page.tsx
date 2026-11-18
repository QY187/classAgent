"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";
import { downloadCourseArchive } from "../../../../lib/course-export";
import ExportLessonPicker from "../../../../components/ExportLessonPicker";
import "./export.css";

type Course = { id: string; name: string };
type Lesson = { id: string; title: string; lesson_date?: string | null };
export default function CourseExportPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Course | null>(null), [lessons, setLessons] = useState<Lesson[]>([]);
  const [scope, setScope] = useState("all"), [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setCourse(null); setLessons([]); setSelected([]); setError(""); setNotice("");
    Promise.all([request<Course[]>("/courses", { signal: controller.signal }), request<Lesson[]>(`/courses/${courseId}/lessons`, { signal: controller.signal })])
      .then(([courses, items]) => { if (!controller.signal.aborted) { setCourse(courses.find((item) => item.id === courseId) || null); setLessons(items); } })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); active.current?.abort(); };
  }, [courseId]);
  async function download() {
    if (!course || busy || loading || (scope === "selected" && !selected.length)) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setError(""); setNotice("");
    const timeout = setTimeout(() => controller.abort("timeout"), 175000);
    try {
      await downloadCourseArchive(courseId, course.name, { lesson_ids: scope === "selected" ? selected : null }, controller.signal);
      if (!controller.signal.aborted) setNotice("ZIP已生成，浏览器已开始下载。解压后先打开「课程目录.md」。");
    } catch (err) { if (!controller.signal.aborted) setError(errorMessage(err)); else if (controller.signal.reason === "timeout") setError("等待导出超时，请减少课次后重试。"); }
    finally { clearTimeout(timeout); if (active.current === controller) { active.current = null; setBusy(false); } }
  }
  return <main className="content course-export-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">↓</span><div className="page-hero-copy"><div className="eyebrow">{course?.name || "课程资料"}</div><h1>课程打包导出</h1><p>按课次整理已保存的资料，下载后离线阅读与备份。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href={`/courses/${courseId}`}>返回课程</Link></div></section>
    {error && <p className="notice" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    {loading ? <p role="status">正在读取课程资料…</p> : !course ? <section className="panel panel-body"><p>课程不存在或当前无法访问。</p></section> : <div className="course-export-layout">
      <section className="panel"><div className="panel-header"><h2>选择导出范围</h2><span>共 {lessons.length} 节课</span></div><div className="panel-body">
        <fieldset className="export-scope" disabled={busy}><legend className="sr-only">导出范围</legend><label><input type="radio" name="export-scope" value="all" checked={scope === "all"} onChange={() => setScope("all")} /><span>整门课程<small>按课程中的课次顺序整理</small></span></label><label><input type="radio" name="export-scope" value="selected" checked={scope === "selected"} onChange={() => setScope("selected")} /><span>指定课次<small>只打包选中的课次</small></span></label></fieldset>
        {scope === "selected" && <ExportLessonPicker lessons={lessons} selected={selected} onChange={setSelected} disabled={busy} />}
        {scope === "selected" && !selected.length && <p className="export-hint">请先选择至少一节课。</p>}
      </div></section>
      <aside className="panel export-package-preview"><div className="panel-header"><h2>你的资料包</h2></div><div className="panel-body"><strong>{course.name}</strong><p>课程目录 + {scope === "all" ? lessons.length : selected.length} 个课次文件夹</p><ul><li>智能纪要 · Markdown</li><li>文字记录 · TXT</li></ul><p className="export-hint">保留已保存的手动修改和说话人名称。缺少的内容会在目录中说明，导出不会调用AI生成资料。</p><button className="button button-primary" disabled={busy || (scope === "selected" && !selected.length)} onClick={download}>{busy ? "正在整理资料…" : "下载课程 ZIP"}</button>{busy && <button type="button" className="button button-quiet" onClick={() => { active.current?.abort(); setBusy(false); setNotice("已取消等待，你可以调整范围后重新导出。"); }}>取消等待</button>}<p className="export-hint">资料较多时建议分批导出。每次最多512MB原始内容、2000个文件。</p></div></aside>
    </div>}
  </main>;
}
