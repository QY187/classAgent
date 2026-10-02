"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import CourseQa from "../../../../components/CourseQa";

export default function CourseAskPage() {
  const { courseId } = useParams<{ courseId: string }>();

  return <main className="content">
    <Link className="back-link" href={`/courses/${courseId}`}>← 返回课次记录</Link>
    <CourseQa courseId={courseId} />
  </main>;
}
