"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";
import type { Quiz, QuizListItem } from "../../../../lib/quizzes";
import type { Material } from "../../../../lib/materials";
import QuizLessonPicker from "../../../../components/QuizLessonPicker";

type Course = { id: string; name: string };
type Lesson = { id: string; title: string };

function QuizLibrary() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const [course, setCourse] = useState<Course | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [quizzes, setQuizzes] = useState<QuizListItem[]>([]);
  const [scope, setScope] = useState(params.get("lessonId") ? "selected" : "all");
  const [selectedLessonIds, setSelectedLessonIds] = useState<string[]>(params.get("lessonId") ? [params.get("lessonId")!] : []);
  const [sourceType, setSourceType] = useState("transcript");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [count, setCount] = useState(5);
  const [questionType, setQuestionType] = useState("mixed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const lessonId = params.get("lessonId");
    setScope(lessonId ? "selected" : "all");
    setSelectedLessonIds(lessonId ? [lessonId] : []);
  }, [courseId, params]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setCourse(null); setLessons([]); setQuizzes([]); setMaterials([]); setMaterialIds([]); setError("");
    Promise.all([request<Course[]>("/courses", { signal: controller.signal }), request<Lesson[]>(`/courses/${courseId}/lessons`, { signal: controller.signal }), request<QuizListItem[]>(`/courses/${courseId}/quizzes`, { signal: controller.signal }), request<Material[]>(`/courses/${courseId}/materials`, { signal: controller.signal })])
      .then(([courses, items, saved, files]) => {
        if (controller.signal.aborted) return;
        setCourse(courses.find((item) => item.id === courseId) || null); setLessons(items); setQuizzes(saved); setMaterials(files);
        setSelectedLessonIds((current) => current.filter((id) => items.some((lesson) => lesson.id === id)));
      })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [courseId]);

  const availableMaterials = materials.filter((item) => item.indexed && (scope === "all" || !!item.lesson_id && selectedLessonIds.includes(item.lesson_id)));
  const selectedMaterials = materialIds.filter((id) => availableMaterials.some((file) => file.id === id));

  async function generate() {
    if (busy || loading || !course || (sourceType === "material" && !selectedMaterials.length) || (scope === "selected" && !selectedLessonIds.length)) return;
    setBusy(true); setError("");
    try {
      const quiz = await request<Quiz>(`/courses/${courseId}/quizzes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_type: sourceType, material_ids: sourceType === "material" ? selectedMaterials : null, lesson_ids: scope === "selected" ? selectedLessonIds : null, count, question_type: questionType }), signal: AbortSignal.timeout(175000),
      });
      router.push(`/quizzes/${quiz.id}`);
    } catch (err) { setError(errorMessage(err)); setBusy(false); }
  }

  function scopeLabel(quiz: QuizListItem) {
    const ids = quiz.lesson_ids ?? (quiz.lesson_id ? [quiz.lesson_id] : []);
    if (!ids.length) return "整门课程";
    return ids.map((id) => lessons.find((lesson) => lesson.id === id)?.title || "课次已不可用").join("、");
  }

  return <main className="content">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">◇</span><div className="page-hero-copy"><div className="eyebrow">{course?.name || "课程"}</div><h1>课堂小测</h1><p>从课堂记录或已解析课件出题，提交后可核对来源。</p></div><div className="page-hero-actions"><Link className="button button-primary" href={`/wrong-questions?course=${courseId}`}>查看本课程错题</Link><Link className="button button-secondary" href={`/courses/${courseId}`}>返回课程</Link></div></section>
    {error && <p className="notice" role="alert">{error}</p>}
    <section className="panel quiz-generate-panel">
      <div className="panel-header"><div><h2>生成一组题</h2><span>生成后直接答题，提交后查看答案、解析与来源依据。</span></div></div>
      <div className="panel-body quiz-generate-body">
        <label className="field-label quiz-setting-count">资料来源<select className="field" value={sourceType} onChange={(event) => setSourceType(event.target.value)} disabled={busy || loading}><option value="transcript">课堂文字记录</option><option value="material">已解析课件</option></select></label>
        <label className="field-label quiz-setting-count">出题范围<select className="field" value={scope} onChange={(event) => setScope(event.target.value)} disabled={busy || loading}><option value="all">整门课程</option><option value="selected">指定课次</option></select></label>
        <label className="field-label quiz-setting-count">题目数量<select className="field" value={count} onChange={(event) => setCount(Number(event.target.value))} disabled={busy}>{[5, 10, 15].map((value) => <option value={value} key={value}>{value} 道</option>)}</select></label>
        <label className="field-label quiz-setting-count">题型<select className="field" value={questionType} onChange={(event) => setQuestionType(event.target.value)} disabled={busy}><option value="mixed">单选 + 判断</option><option value="single_choice">仅单选题</option><option value="true_false">仅判断题</option></select></label>
        {scope === "selected" && <QuizLessonPicker key={courseId} lessons={lessons} selectedIds={selectedLessonIds} onChange={setSelectedLessonIds} disabled={busy || loading} />}
        {scope === "selected" && !selectedLessonIds.length && <p className="quiz-settings-hint">请先选择至少一节课。</p>}
        {sourceType === "material" && <fieldset className="quiz-material-picker" disabled={busy || loading}><legend>选择课件（最多50份）</legend>{availableMaterials.length ? availableMaterials.map((file) => <label className="field-label" key={file.id}><input type="checkbox" checked={selectedMaterials.includes(file.id)} disabled={!selectedMaterials.includes(file.id) && selectedMaterials.length >= 50} onChange={(event) => setMaterialIds(event.target.checked ? [...selectedMaterials, file.id] : selectedMaterials.filter((id) => id !== file.id))} /><span>{file.filename}</span></label>) : <p>当前范围没有可用课件，请先在课程资料中加入问答并等待解析完成。</p>}</fieldset>}
        <button className="button button-primary" type="button" disabled={busy || loading || !course || (sourceType === "material" && !selectedMaterials.length) || (scope === "selected" && !selectedLessonIds.length)} onClick={generate}>{busy ? "正在出题并核验…" : `生成 ${count} 道题`}</button>
        <p className="quiz-settings-hint">分批出题与答案核验可能需要两到三分钟，请等待完成。</p>
        <p className="quiz-settings-hint">目标题数可选，实际题数以通过来源与答案核验的题目为准。</p>
      </div>
    </section>
    <section className="panel"><div className="panel-header"><h2>历史小测</h2><span>{quizzes.length} 组</span></div><div className="panel-body">{loading ? <p role="status">正在加载…</p> : quizzes.length ? <div className="quiz-list">{quizzes.map((quiz) => <Link className="quiz-list-row" href={`/quizzes/${quiz.id}`} key={quiz.id}><div><strong>{quiz.title}</strong><span>{quiz.question_count} 道题 · {scopeLabel(quiz)} · {new Date(quiz.created_at).toLocaleDateString("zh-CN")}</span></div><span className="quiz-status">开始答题 →</span></Link>)}</div> : <div className="empty-state"><strong>还没有课堂小测</strong><p>选择范围后生成第一组题。</p></div>}</div></section>
  </main>;
}

export default function Page() { return <Suspense fallback={<main className="content"><p role="status">正在加载小测…</p></main>}><QuizLibrary /></Suspense>; }
