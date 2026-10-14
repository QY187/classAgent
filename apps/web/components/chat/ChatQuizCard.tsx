import Link from "next/link";
import type { QuizArtifact } from "../../lib/chat";

export default function ChatQuizCard({ quiz }: { quiz: QuizArtifact }) {
  return <section className="chat-quiz-card" aria-label="已生成的课堂小测">
    <div className="chat-quiz-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="3" width="14" height="18" rx="3"/><path d="m8 9 1.5 1.5L12 8m2 2h2M8 15h8"/></svg></div>
    <div className="chat-quiz-info"><span>课堂小测已生成</span><h3>{quiz.title}</h3><p>{quiz.course_name} · {quiz.question_count} 道题 · {quiz.lesson_ids.length ? `指定 ${quiz.lesson_ids.length} 节课` : "整门课程"}</p><small>提交答案后查看成绩、答案与解析</small></div>
    <Link className="button button-primary" href={`/quizzes/${encodeURIComponent(quiz.id)}`}>开始答题 <span aria-hidden="true">→</span></Link>
  </section>;
}
