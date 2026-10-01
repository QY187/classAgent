"use client";

import { useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";

type Lesson = { id: string; title: string };
type Material = { id: string; lesson_id: string | null; filename: string; size_bytes: number; created_at: string; status: string };

function sizeLabel(bytes: number) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function CourseMaterials({ courseId, lessons, refreshKey }: { courseId: string; lessons: Lesson[]; refreshKey: number }) {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    request<Material[]>(`/courses/${courseId}/materials`).then(setMaterials).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false));
  }, [courseId, refreshKey]);

  return <section className="panel course-materials">
    <div className="panel-header"><div><h2>资料库</h2><span className="material-subtitle">集中保存这门课的讲义、课件和补充资料</span></div><span>{materials.length} 份资料</span></div>
    <div className="panel-body">
      <p className="material-hint">在下方对应课次点击“上传资料”，可一次选择多个文件。支持 PDF、PPT、Word、图片和文本，单个文件最大 25 MB。</p>
      {error && <p className="notice" role="alert">{error}</p>}
      {loading ? <p role="status" className="material-muted">正在加载资料…</p> : materials.length === 0 ? <div className="material-empty">还没有资料，上传讲义或课件后会显示在这里。</div> : <div className="material-list">{materials.map((material) => <div className="material-row" key={material.id}>
        <span className="material-icon" aria-hidden="true">▤</span>
        <div className="material-info"><strong title={material.filename}>{material.filename}</strong><span>{material.lesson_id ? lessons.find((lesson) => lesson.id === material.lesson_id)?.title || "关联课次" : "整门课程"} · {sizeLabel(material.size_bytes)} · {new Date(material.created_at).toLocaleDateString("zh-CN")} · {material.status === "stored" ? "已保存" : material.status}</span></div>
      </div>)}</div>}
    </div>
  </section>;
}
