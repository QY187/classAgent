export type RecycledKind = "course" | "lesson" | "material";
export type RecycledItem = {
  id: string;
  kind: RecycledKind;
  title: string;
  course_name: string;
  lesson_title: string | null;
  deleted_at: string;
  expires_at: string;
};
export const recycledKindLabel: Record<RecycledKind, string> = { course: "课程", lesson: "课次", material: "资料" };
export function recycledKey(item: RecycledItem): string { return `${item.kind}/${item.id}`; }
