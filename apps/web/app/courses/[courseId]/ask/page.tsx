import { redirect } from "next/navigation";

export default async function CourseAskPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  redirect(`/chat?course=${encodeURIComponent(courseId)}`);
}
