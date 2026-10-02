export type QuizQuestion = {
  id: string;
  kind: "single_choice" | "true_false";
  stem: string;
  options: string[];
  correct_option?: number;
  explanation?: string;
  source_lesson_id: string | null;
  source_start_ms: number;
  source_excerpt: string;
};

export type Quiz = {
  id: string;
  course_id: string;
  lesson_id: string | null;
  title: string;
  status: "draft" | "ready";
  created_at: string;
  questions: QuizQuestion[];
};

export type QuizListItem = Pick<Quiz, "id" | "title" | "lesson_id" | "status" | "created_at"> & { question_count: number };

export type QuizAttemptItem = { id: string; correct_count: number; total_count: number; created_at: string };
export type QuizAttempt = QuizAttemptItem & {
  quiz_id: string;
  course_id: string;
  title: string;
  questions: (QuizQuestion & { selected_option: number; correct_option: number; is_correct: boolean; explanation: string; source_segment_id: string | null })[];
};

export function quizSourceUrl(question: QuizQuestion): string | null {
  return question.source_lesson_id ? `/lessons/${question.source_lesson_id}/transcript?t=${question.source_start_ms}` : null;
}
