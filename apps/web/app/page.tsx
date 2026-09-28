"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { apiUrl, errorMessage, request } from "../lib/api";

type Course = { id: string; name: string; semester?: string | null; created_at: string };

export default function Home() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState("");
  const [semester, setSemester] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadCourses() {
    try {
      setCourses(await request<Course[]>("/courses"));
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadCourses(); }, []);

  async function createCourse(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    if (saving) return;
    setSaving(true);
    setMessage("");
    try {
      const course = await request<Course>("/courses", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), semester: semester.trim() || null }) });
      setCourses((items) => [course, ...items]);
      setName("");
      setSemester("");
      setShowModal(false);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="content">
      <div className="page-heading">
        <div><div className="eyebrow">我的课程库</div><h1>把每一节课，变成可复习的资料</h1><p>录音、转写和纪要会按课程持续整理在这里。</p></div>
        <button className="button button-primary" onClick={() => setShowModal(true)}>＋ 新建课程</button>
      </div>
      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">课程总数</div><div className="stat-value">{courses.length}</div><div className="stat-note">持续积累你的学习资料</div></div>
        <div className="stat-card"><div className="stat-label">待处理课次</div><div className="stat-value">—</div><div className="stat-note">课次统计即将开放</div></div>
        <div className="stat-card"><div className="stat-label">最近学习</div><div className="stat-value">—</div><div className="stat-note">学习统计即将开放</div></div>
      </div>
      <div className="section-head"><h2>最近课程</h2><span>{courses.length ? `${courses.length} 门课程` : "还没有课程"}</span></div>
      {message && <div className="notice" style={{ marginBottom: 16 }}>{message}</div>}
      {loading ? <div className="empty-state"><div className="empty-icon">◌</div><p>正在加载课程…</p></div> : courses.length === 0 ? (
        <div className="empty-state"><div className="empty-icon">▱</div><strong>从第一门课程开始</strong><p>创建课程后，上传音频并获得带时间点的课堂记录。</p><button className="button button-primary" onClick={() => setShowModal(true)}>创建第一门课程</button></div>
      ) : (
        <div className="course-grid">{courses.map((course) => <Link href={`/courses/${course.id}`} className="course-card" key={course.id}><div className="course-color" /><h3>{course.name}</h3><div className="course-meta">{course.semester || "未设置学期"}</div><div className="course-foot"><span>进入课程</span><span>→</span></div></Link>)}</div>
      )}
      {showModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowModal(false); }}><form className="modal" role="dialog" aria-modal="true" aria-label="创建资料" onKeyDown={(event) => { if (event.key === "Escape" && !saving) setShowModal(false); }} onSubmit={createCourse}><h2>新建课程</h2>{message && <p role="alert" className="notice">{message}</p>}<div className="form-grid"><label className="field-label">课程名称<input className="field" required maxLength={200} autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：数据结构" /></label><label className="field-label">学期（可选）<input className="field" value={semester} onChange={(event) => setSemester(event.target.value)} placeholder="例如：2026 秋季" /></label></div><div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setShowModal(false)}>取消</button><button className="button button-primary" type="submit" disabled={saving}>{saving ? "创建中…" : "创建课程"}</button></div></form></div>}
    </main>
  );
}
