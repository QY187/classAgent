"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import { QuizAttempt, quizSourceUrl } from "../../../lib/quizzes";

export default function QuizResultPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const [result, setResult] = useState<QuizAttempt | null>(null);
  const [error, setError] = useState("");
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedCards, setAddedCards] = useState<Record<string, string>>({});
  const [cardError, setCardError] = useState<Record<string, string>>({});
  useEffect(() => { request<QuizAttempt>(`/quiz-attempts/${attemptId}`).then(setResult).catch((err) => setError(errorMessage(err))); }, [attemptId]);

  async function addToReview(questionId: string) {
    setAddingId(questionId);
    setCardError((current) => ({ ...current, [questionId]: "" }));
    try {
      const outcome = await request<{ card_id: string; created: boolean }>(`/quiz-attempts/${attemptId}/questions/${questionId}/review-card`, { method: "POST" });
      setAddedCards((current) => ({ ...current, [questionId]: outcome.card_id }));
    } catch (err) { setCardError((current) => ({ ...current, [questionId]: errorMessage(err) })); }
    finally { setAddingId(null); }
  }
  if (!result) return <main className="content"><p role={error ? "alert" : "status"}>{error || "正在加载答题结果…"}</p></main>;
  return <main className="content"><section className="page-hero page-hero-compact"><span className="page-hero-icon">✓</span><div className="page-hero-copy"><div className="eyebrow">课堂小测 · 答题结果</div><h1>{result.correct_count} / {result.total_count} 题正确</h1><p>{result.title} · {new Date(result.created_at).toLocaleString("zh-CN")}</p></div><div className="page-hero-actions"><Link className="button button-primary" href={`/wrong-questions?course=${result.course_id}`}>查看错题本</Link><Link className="button button-secondary" href={`/quizzes/${result.quiz_id}`}>再做一次</Link><Link className="button button-secondary" href={`/courses/${result.course_id}/quizzes`}>返回小测列表</Link></div></section><p className="wrong-book-result-hint">答错的题已自动收录到错题本，可以单独重做并查看巩固情况。</p><div className="quiz-question-list">{result.questions.map((question, index) => <section className={`panel quiz-result-question${question.is_correct ? " is-correct" : " is-wrong"}`} key={question.id} id={`question-${question.id}`}><div className="panel-header"><h2>第 {index + 1} 题</h2><span>{question.is_correct ? "回答正确" : "需要复习"}</span></div><div className="panel-body"><h3>{question.stem}</h3><div className="quiz-result-options">{question.options.map((option, optionIndex) => <div className={`quiz-result-option${optionIndex === question.correct_option ? " is-answer" : ""}${optionIndex === question.selected_option && !question.is_correct ? " is-wrong-choice" : ""}`} key={optionIndex}>{String.fromCharCode(65 + optionIndex)}. {option}{optionIndex === question.correct_option && <b>正确答案</b>}{optionIndex === question.selected_option && <small>你的选择</small>}</div>)}</div><div className="quiz-result-explanation"><strong>解析</strong><p>{question.explanation}</p></div><div className="quiz-evidence"><strong>课堂依据</strong><p>{question.source_excerpt}</p>{quizSourceUrl(question) && <Link href={quizSourceUrl(question)!}>回到文字记录 ↗</Link>}</div>{!question.is_correct && question.source_lesson_id && <div className="quiz-wrong-actions">{addedCards[question.id] ? <Link className="button button-secondary" href={`/lessons/${question.source_lesson_id}/review`}>已加入知识点 · 去复习 →</Link> : <button className="button button-secondary" type="button" disabled={addingId === question.id} onClick={() => addToReview(question.id)}>{addingId === question.id ? "正在加入…" : "加入知识点清单"}</button>}{cardError[question.id] && <span role="alert">{cardError[question.id]}</span>}</div>}</div></section>)}</div></main>;
}
