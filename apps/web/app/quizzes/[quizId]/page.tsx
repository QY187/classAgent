"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { errorMessage, request } from "../../../lib/api";
import { Quiz, QuizQuestion, quizSourceUrl } from "../../../lib/quizzes";

function DraftQuestion({ question, quizId, onSaved }: { question: QuizQuestion; quizId: string; onSaved: (quiz: Quiz) => void }) {
  const [stem, setStem] = useState(question.stem);
  const [options, setOptions] = useState(question.options);
  const [correct, setCorrect] = useState(question.correct_option ?? 0);
  const [explanation, setExplanation] = useState(question.explanation || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      onSaved(await request<Quiz>(`/quizzes/${quizId}/questions/${question.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stem, options, correct_option: correct, explanation }),
      }));
    } catch (err) { setError(errorMessage(err)); }
    finally { setSaving(false); }
  }

  const sourceUrl = quizSourceUrl(question);
  return <form className="quiz-question" onSubmit={save}><div className="quiz-question-head"><span>{question.kind === "true_false" ? "判断题" : "单选题"}</span>{sourceUrl && <Link href={sourceUrl}>核对课堂原文 ↗</Link>}</div><label className="field-label">题目<textarea className="field" rows={2} maxLength={500} required value={stem} onChange={(event) => setStem(event.target.value)} /></label><div className="quiz-options">{options.map((option, index) => <label className="field-label" key={index}>选项 {String.fromCharCode(65 + index)}<input className="field" value={option} maxLength={200} required disabled={question.kind === "true_false"} onChange={(event) => setOptions((current) => current.map((item, i) => i === index ? event.target.value : item))} /></label>)}</div><label className="field-label">正确答案<select className="field" value={correct} onChange={(event) => setCorrect(Number(event.target.value))}>{options.map((_, index) => <option key={index} value={index}>{String.fromCharCode(65 + index)}</option>)}</select></label><label className="field-label">解析<textarea className="field" rows={2} maxLength={2000} required value={explanation} onChange={(event) => setExplanation(event.target.value)} /></label><div className="quiz-evidence"><strong>课堂依据</strong><p>{question.source_excerpt}</p></div>{error && <p className="notice" role="alert">{error}</p>}<div className="quiz-question-actions"><button className="button button-secondary" disabled={saving}>{saving ? "保存中…" : "保存本题修改"}</button></div></form>;
}

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>();
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { request<Quiz>(`/quizzes/${quizId}`).then(setQuiz).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false)); }, [quizId]);

  async function publish() {
    if (busy) return;
    setBusy(true); setError("");
    try { setQuiz(await request<Quiz>(`/quizzes/${quizId}/publish`, { method: "POST" })); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="content"><p role="status">正在加载小测…</p></main>;
  if (!quiz) return <main className="content"><p className="notice" role="alert">{error || "小测不存在"}</p></main>;
  return <main className="content"><section className="page-hero page-hero-compact"><span className="page-hero-icon">◇</span><div className="page-hero-copy"><div className="eyebrow">课堂小测 · {quiz.status === "draft" ? "核对草稿" : "准备答题"}</div><h1>{quiz.title}</h1><p>{quiz.questions.length} 道题 · {quiz.status === "draft" ? "请先核对题目、答案和课堂依据" : "每道题都可查看课堂来源"}</p></div><div className="page-hero-actions"><Link className="button button-secondary" href={`/courses/${quiz.course_id}/quizzes`}>返回小测列表</Link></div></section>{error && <p className="notice" role="alert">{error}</p>}{quiz.status === "draft" ? <><div className="quiz-draft-note">AI 生成的答案可能出错。请对照每题的课堂依据检查并修改，确认后再开始答题。</div><div className="quiz-question-list">{quiz.questions.map((question, index) => <section className="panel" key={question.id}><div className="panel-header"><h2>第 {index + 1} 题</h2></div><div className="panel-body"><DraftQuestion question={question} quizId={quiz.id} onSaved={setQuiz} /></div></section>)}</div><div className="quiz-publish-bar"><button className="button button-primary" disabled={busy} onClick={publish}>{busy ? "正在准备…" : "已核对，开始答题"}</button></div></> : <section className="panel"><div className="panel-body"><p>题目已准备好。答题功能正在接入。</p></div></section>}</main>;
}
