"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../../lib/api";

type Course = { id: string; name: string };
type Progress = {
  course_id: string;
  lesson_total: number;
  transcript_lessons: number;
  summary_lessons: number;
  review_cards: { total: number; new: number; review: number; mastered: number };
  quizzes: {
    attempt_count: number;
    average_score: number | null;
    wrong_question_count: number;
    recent_attempt: { id: string; title: string; correct_count: number; total_count: number; created_at: string } | null;
  };
};

export default function CourseProgressPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Course | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      request<Course[]>("/courses"),
      request<Progress>(`/courses/${courseId}/progress`),
    ]).then(([courses, result]) => {
      if (!active) return;
      setCourse(courses.find((item) => item.id === courseId) ?? null);
      setProgress(result);
    }).catch((cause) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [courseId]);

  if (error) return <main className="content"><div className="notice">{error}</div><Link href={`/courses/${courseId}`}>返回课程</Link></main>;
  if (!progress) return <main className="content"><p role="status">正在加载学习进度…</p></main>;

  return <main className="content course-progress-page">
    <div className="breadcrumb"><Link href={`/courses/${courseId}`}>{course?.name ?? "课程"}</Link><span> / 学习进度</span></div>
    <section className="page-hero page-hero-compact">
      <span className="page-hero-icon">▥</span>
      <div className="page-hero-copy"><div className="eyebrow">课程概览</div><h1>学习进度</h1><p>从课次内容、知识点状态和小测记录了解这门课的学习情况。</p></div>
    </section>
    <section className="panel course-progress-panel">
      <div className="panel-header"><h2>课堂内容</h2><span>按课次统计</span></div>
      <div className="course-progress-grid">
        <div className="course-progress-metric"><span>课次总数</span><strong>{progress.lesson_total}</strong><small>已创建的课次</small></div>
        <div className="course-progress-metric"><span>已有文字记录</span><strong>{progress.transcript_lessons}<em> / {progress.lesson_total}</em></strong><small>至少有一段转写的课次</small></div>
        <div className="course-progress-metric"><span>已有智能纪要</span><strong>{progress.summary_lessons}<em> / {progress.lesson_total}</em></strong><small>已生成或编辑并保存纪要的课次</small></div>
      </div>
      <div className="course-progress-footer"><Link href={`/courses/${courseId}`}>查看课次记录 →</Link></div>
    </section>
    <section className="panel course-progress-panel">
      <div className="panel-header"><h2>知识点掌握状态</h2><span>共 {progress.review_cards.total} 个</span></div>
      <div className="course-progress-grid">
        <Link className="course-progress-metric course-progress-metric-link" href={`/review?course=${courseId}&status=new`}><span>未学习</span><strong>{progress.review_cards.new}</strong><small>点击查看知识点 →</small></Link>
        <Link className="course-progress-metric course-progress-metric-link" href={`/review?course=${courseId}&status=review`}><span>需要复习</span><strong>{progress.review_cards.review}</strong><small>点击查看知识点 →</small></Link>
        <Link className="course-progress-metric course-progress-metric-link" href={`/review?course=${courseId}&status=mastered`}><span>已掌握</span><strong>{progress.review_cards.mastered}</strong><small>点击查看知识点 →</small></Link>
      </div>
      <div className="course-progress-footer"><Link href={`/review?course=${courseId}`}>查看这门课的全部知识点 →</Link></div>
    </section>
    <section className="panel course-progress-panel">
      <div className="panel-header"><h2>课堂小测</h2><span>仅统计我的答题记录</span></div>
      <div className="course-progress-grid">
        <div className="course-progress-metric"><span>作答次数</span><strong>{progress.quizzes.attempt_count}</strong><small>重复作答也计入</small></div>
        <div className="course-progress-metric"><span>平均得分</span><strong>{progress.quizzes.average_score === null ? "—" : `${progress.quizzes.average_score}%`}</strong><small>每次小测正确率的平均值</small></div>
        <div className="course-progress-metric"><span>曾答错的题目</span><strong>{progress.quizzes.wrong_question_count}</strong><small>同一道题只计一次</small></div>
      </div>
      {progress.quizzes.recent_attempt && <div className="course-progress-recent">
        <div><span>最近一次作答</span><strong>{progress.quizzes.recent_attempt.title}</strong><small>{new Date(progress.quizzes.recent_attempt.created_at).toLocaleString("zh-CN")} · 答对 {progress.quizzes.recent_attempt.correct_count} / {progress.quizzes.recent_attempt.total_count} 题</small></div>
        <Link href={`/quiz-attempts/${progress.quizzes.recent_attempt.id}`}>查看结果 →</Link>
      </div>}
      <div className="course-progress-footer"><Link href={`/courses/${courseId}/quizzes`}>查看课堂小测 →</Link></div>
    </section>
  </main>;
}
