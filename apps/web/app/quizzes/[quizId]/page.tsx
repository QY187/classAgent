"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import { Quiz, QuizAttempt, QuizAttemptItem } from "../../../lib/quizzes";

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>();
  const router = useRouter();
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [attempts, setAttempts] = useState<QuizAttemptItem[]>([]);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { request<Quiz>(`/quizzes/${quizId}`).then(setQuiz).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false)); }, [quizId]);
  useEffect(() => { if (quiz) request<QuizAttemptItem[]>(`/quizzes/${quizId}/attempts`).then(setAttempts).catch(() => {}); }, [quizId, quiz?.status]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!quiz || busy || quiz.questions.some((question) => answers[question.id] === undefined)) return;
    setBusy(true); setError("");
    try {
      const result = await request<QuizAttempt>(`/quizzes/${quizId}/attempts`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers }),
      });
      router.push(`/quiz-attempts/${result.id}`);
    } catch (err) { setError(errorMessage(err)); setBusy(false); }
  }

  if (loading) return <main className="content"><p role="status">正在加载小测…</p></main>;
  if (!quiz) return <main className="content"><p className="notice" role="alert">{error || "小测不存在"}</p></main>;
  return <main className="content"><section className="page-hero page-hero-compact"><span className="page-hero-icon">◇</span><div className="page-hero-copy"><div className="eyebrow">课堂小测 · 开始答题</div><h1>{quiz.title}</h1><p>{quiz.questions.length} 道题 · 答完全部题目后统一提交，随后查看答案、解析与课堂依据</p></div><div className="page-hero-actions"><Link className="button button-secondary" href={`/courses/${quiz.course_id}/quizzes`}>返回小测列表</Link></div></section>{error && <p className="notice" role="alert">{error}</p>}<form onSubmit={submit}><div className="quiz-question-list">{quiz.questions.map((question, index) => <section className="panel" key={question.id}><div className="panel-header"><h2>第 {index + 1} 题 <span className="quiz-kind">{question.kind === "true_false" ? "判断题" : "单选题"}</span></h2></div><div className="panel-body"><fieldset className="quiz-answer-fieldset"><legend>{question.stem}</legend>{question.options.map((option, optionIndex) => <label className={`quiz-answer-option${answers[question.id] === optionIndex ? " is-selected" : ""}`} key={optionIndex}><input type="radio" name={question.id} checked={answers[question.id] === optionIndex} onChange={() => setAnswers((current) => ({ ...current, [question.id]: optionIndex }))} /><span>{String.fromCharCode(65 + optionIndex)}. {option}</span></label>)}</fieldset></div></section>)}</div><div className="quiz-publish-bar"><button className="button button-primary" disabled={busy || quiz.questions.some((question) => answers[question.id] === undefined)}>{busy ? "正在提交…" : `提交答案（${Object.keys(answers).length}/${quiz.questions.length}）`}</button></div></form>{attempts.length > 0 && <section className="panel quiz-history"><div className="panel-header"><h2>历史成绩</h2><span>{attempts.length} 次</span></div><div className="panel-body quiz-list">{attempts.map((attempt) => <Link className="quiz-list-row" href={`/quiz-attempts/${attempt.id}`} key={attempt.id}><div><strong>{attempt.correct_count} / {attempt.total_count} 题正确</strong><span>{new Date(attempt.created_at).toLocaleString("zh-CN")}</span></div><span className="quiz-status">查看解析 →</span></Link>)}</div></section>}</main>;
}
