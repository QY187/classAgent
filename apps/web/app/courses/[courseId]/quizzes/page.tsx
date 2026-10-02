"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";
import type { Quiz, QuizListItem } from "../../../../lib/quizzes";

type Course = { id: string; name: string };
type Lesson = { id: string; title: string };

function QuizLibrary() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const [course, setCourse] = useState<Course | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [quizzes, setQuizzes] = useState<QuizListItem[]>([]);
  const [lessonId, setLessonId] = useState(params.get("lessonId") || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([request<Course[]>("/courses"), request<Lesson[]>(`/courses/${courseId}/lessons`), request<QuizListItem[]>(`/courses/${courseId}/quizzes`)])
      .then(([courses, items, saved]) => { setCourse(courses.find((item) => item.id === courseId) || null); setLessons(items); setQuizzes(saved); })
      .catch((err) => setError(errorMessage(err))).finally(() => setLoading(false));
  }, [courseId]);

  async function generate() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const quiz = await request<Quiz>(`/courses/${courseId}/quizzes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lesson_id: lessonId || null, count: 5 }), signal: AbortSignal.timeout(130000),
      });
      router.push(`/quizzes/${quiz.id}`);
    } catch (err) { setError(errorMessage(err)); setBusy(false); }
  }

  return <main className="content">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">◇</span><div className="page-hero-copy"><div className="eyebrow">{course?.name || "课程"}</div><h1>课堂小测</h1><p>从课堂文字记录出题，每道题都能回到原文核对。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href={`/courses/${courseId}`}>返回课程</Link></div></section>
    {error && <p className="notice" role="alert">{error}</p>}
    <section className="panel quiz-generate-panel"><div className="panel-header"><div><h2>生成一组题</h2><span>生成后先检查题目、答案与来源，再开始答题。</span></div></div><div className="panel-body quiz-generate-body"><label className="field-label">出题范围<select className="field" value={lessonId} onChange={(event) => setLessonId(event.target.value)} disabled={busy}><option value="">整门课程</option>{lessons.map((lesson) => <option value={lesson.id} key={lesson.id}>{lesson.title}</option>)}</select></label><button className="button button-primary" type="button" disabled={busy || loading || !course} onClick={generate}>{busy ? "正在生成题目…" : "生成 5 道题"}</button></div></section>
    <section className="panel"><div className="panel-header"><h2>历史小测</h2><span>{quizzes.length} 组</span></div><div className="panel-body">{loading ? <p role="status">正在加载…</p> : quizzes.length ? <div className="quiz-list">{quizzes.map((quiz) => <Link className="quiz-list-row" href={`/quizzes/${quiz.id}`} key={quiz.id}><div><strong>{quiz.title}</strong><span>{quiz.question_count} 道题 · {quiz.lesson_id ? lessons.find((lesson) => lesson.id === quiz.lesson_id)?.title || "课次" : "整门课程"} · {new Date(quiz.created_at).toLocaleDateString("zh-CN")}</span></div><span className="quiz-status">{quiz.status === "draft" ? "待核对" : "开始答题"} →</span></Link>)}</div> : <div className="empty-state"><strong>还没有课堂小测</strong><p>选择范围后生成第一组题。</p></div>}</div></section>
  </main>;
}

export default function Page() { return <Suspense fallback={<main className="content"><p role="status">正在加载小测…</p></main>}><QuizLibrary /></Suspense>; }
