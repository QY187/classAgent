"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { errorMessage, request } from "../lib/api";
import { quizSourceUrl, type WrongQuestion, type WrongQuestionResult } from "../lib/quizzes";
import WrongPracticeSummary, { type PracticeAnswer } from "./WrongPracticeSummary";

type Props = {
  questions: WrongQuestion[];
  onResult: (questionId: string, result: WrongQuestionResult) => void;
  onClose: () => void;
};

export default function WrongQuestionPractice({ questions, onResult, onClose }: Props) {
  const [roundQuestions, setRoundQuestions] = useState(questions);
  const [answers, setAnswers] = useState<PracticeAnswer[]>([]);
  const [index, setIndex] = useState(0);
  const [selection, setSelection] = useState<number | null>(null);
  const [result, setResult] = useState<WrongQuestionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [finished, setFinished] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const submitting = useRef(false);
  const question = roundQuestions[index];

  useEffect(() => { heading.current?.focus(); }, [question.id, finished]);

  async function submit() {
    if (selection === null || submitting.current || result) return;
    submitting.current = true;
    setBusy(true); setError("");
    try {
      const outcome = await request<WrongQuestionResult>(`/wrong-questions/${question.id}/retries`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_option: selection }),
      });
      setResult(outcome);
      setAnswers((current) => [...current, { question, result: outcome }]);
      onResult(question.id, outcome);
    } catch (err) { setError(errorMessage(err)); }
    finally { submitting.current = false; setBusy(false); }
  }

  function next() {
    if (!result || busy) return;
    if (index === roundQuestions.length - 1) { setFinished(true); return; }
    setIndex((current) => current + 1);
    setSelection(null); setResult(null); setError("");
  }

  function retryRound(retryQuestions: WrongQuestion[]) {
    if (!retryQuestions.length) return;
    setRoundQuestions(retryQuestions); setAnswers([]); setIndex(0);
    setSelection(null); setResult(null); setError(""); setFinished(false);
  }

  if (finished) return <WrongPracticeSummary total={roundQuestions.length} answers={answers} onRetry={retryRound} onClose={onClose} />;

  return <section className="panel wrong-practice-panel" aria-label="连续重练">
    <div className="panel-header"><h2>错题重练</h2><button className="button button-secondary" disabled={busy} onClick={() => answers.length ? setFinished(true) : onClose()}>结束练习</button></div>
    <div className="panel-body">
      <div className="wrong-practice-progress"><span>第 {index + 1} / {roundQuestions.length} 题</span><span>{question.kind === "true_false" ? "判断题" : "单选题"}</span></div>
      <progress aria-label="本轮作答进度" value={answers.length} max={roundQuestions.length} />
      <div className="wrong-book-meta"><span>{question.course_name}</span><span>{question.quiz_title}</span></div>
      <h3 tabIndex={-1} ref={heading}>{question.stem}</h3>
      <fieldset disabled={busy || !!result} className="wrong-book-choices">
        <legend>选择答案</legend>
        {question.options.map((option, optionIndex) => <label className={`wrong-book-choice${selection === optionIndex ? " is-selected" : ""}${result && result.correct_option === optionIndex ? " is-answer" : ""}${result && !result.is_correct && result.selected_option === optionIndex ? " is-wrong" : ""}`} key={optionIndex}>
          <input type="radio" name={`practice-${question.id}`} checked={selection === optionIndex} onChange={() => setSelection(optionIndex)} />
          <span>{String.fromCharCode(65 + optionIndex)}. {option}</span>
          {result && result.correct_option === optionIndex && <b>正确答案</b>}
        </label>)}
      </fieldset>
      {error && <p className="notice" role="alert">{error} 请重试提交，本题尚未进入下一题。</p>}
      {result ? <div className="wrong-book-feedback">
        <strong role="status">{result.is_correct ? "回答正确，已归入已巩固" : "本次答错，继续保留在待巩固"}</strong>
        <div className="quiz-result-explanation"><strong>解析</strong><p>{result.explanation}</p></div>
        <div className="quiz-evidence"><strong>课堂依据</strong><p>{result.source_excerpt}</p>{quizSourceUrl(result) && <Link href={quizSourceUrl(result)!} target="_blank" rel="noopener noreferrer">回到文字记录 ↗</Link>}</div>
        <button className="button button-primary" onClick={next}>{index === roundQuestions.length - 1 ? "完成本轮" : "下一题"}</button>
      </div> : <button className="button button-primary" disabled={selection === null || busy} onClick={submit}>{busy ? "正在判分…" : error ? "重试提交" : "提交答案"}</button>}
      <p className="wrong-practice-hint">提交后查看解析，再进入下一题。提前结束时，已提交的结果会保留，未作答的题不改变状态。</p>
    </div>
  </section>;
}
