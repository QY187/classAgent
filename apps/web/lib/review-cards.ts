export type CardType = "concept" | "question" | "rule" | "pitfall";
export type CardStatus = "new" | "review" | "mastered";

export type ReviewCard = {
  id: string;
  course_id: string;
  course_name: string;
  lesson_id: string;
  lesson_title: string;
  card_type: CardType;
  title: string;
  body: string;
  status: CardStatus;
  source_segment_id: string | null;
  source_start_ms: number | null;
  source_excerpt: string | null;
  created_at: string;
};

export const cardTypeLabel: Record<CardType, string> = {
  concept: "知识点", question: "问答", rule: "公式与规则", pitfall: "易错点",
};

export const cardStatusLabel: Record<CardStatus, string> = {
  new: "未学习", review: "需要复习", mastered: "已掌握",
};

export function reviewTime(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
