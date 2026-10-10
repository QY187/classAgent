"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { quizSourceUrl, type WrongQuestion, type WrongQuestionResult } from "../lib/quizzes";

export type PracticeAnswer = { question: WrongQuestion; result: WrongQuestionResult };

type Props = {
  total: number;
  answers: PracticeAnswer[];
  onRetry: (questions: WrongQuestion[]) => void;
  onClose: () => void;
};

export default function WrongPracticeSummary({ total, answers, onRetry, onClose }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const correct = answers.filter(({ result }) => result.is_correct).length;
  const wrong = answers.filter(({ result }) => !result.is_correct);
  const remaining = total - answers.length;

  return <section className="panel wrong-practice-panel" aria-label="本轮练习结果">
    <div className="panel-header"><h2 tabIndex={-1} ref={heading}>本轮练习结果</h2><span>已作答 {answers.length} / {total} 题</span></div>
    <div className="panel-body">
      <div className="wrong-practice-stats">
        <div><strong>{correct}</strong><span>答对 · 已巩固</span></div>
        <div><strong>{wrong.length}</strong><span>答错 · 待巩固</span></div>
        <div><strong>{remaining}</strong><span>未作答 · 状态未变</span></div>
      </div>
      <p className="wrong-practice-hint">已提交的结果均已保存到错题本，原课堂小测记录保持不变。</p>
      <div className="wrong-book-actions">
        {wrong.length > 0 && <button className="button button-primary" onClick={() => onRetry(wrong.map(({ question }) => question))}>重练本轮错题（{wrong.length} 道）</button>}
        <button className="button button-secondary" onClick={onClose}>返回错题本</button>
      </div>
      <div className="wrong-practice-results">{answers.map(({ question, result }, index) => <details key={question.id}>
        <summary><span className={`wrong-book-status ${result.is_correct ? "mastered" : "pending"}`}>{result.is_correct ? "答对" : "答错"}</span><span>{index + 1}. {question.stem}</span></summary>
        <div className="wrong-practice-result-body">
          <p>你的答案：{String.fromCharCode(65 + result.selected_option)}. {question.options[result.selected_option]}</p>
          <p>正确答案：{String.fromCharCode(65 + result.correct_option)}. {question.options[result.correct_option]}</p>
          <div className="quiz-result-explanation"><strong>解析</strong><p>{result.explanation}</p></div>
          <div className="quiz-evidence"><strong>课堂依据</strong><p>{result.source_excerpt}</p>{quizSourceUrl(result) && <Link href={quizSourceUrl(result)!} target="_blank" rel="noopener noreferrer">回到文字记录 ↗</Link>}</div>
        </div>
      </details>)}</div>
    </div>
  </section>;
}
