import { authorizedResponse } from "./api";

export type CourseExportOptions = { lesson_ids: string[] | null };

export function courseZipName(title: string): string {
  const name = title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").trim().slice(0, 80);
  return `${name || "课堂"}-课程资料.zip`;
}

export async function downloadCourseArchive(courseId: string, title: string, options: CourseExportOptions, signal: AbortSignal) {
  const response = await authorizedResponse(`/courses/${encodeURIComponent(courseId)}/export`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options), signal,
  });
  if (!response.headers.get("Content-Type")?.startsWith("application/zip")) throw new Error("未收到可用的ZIP文件，请稍后重试。");
  const blob = await response.blob();
  const bytes = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  if (bytes[0] !== 0x50 || bytes[1] !== 0x4b) throw new Error("导出文件不完整，请重新下载。");
  if (signal.aborted) return;
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a"); link.href = url; link.download = courseZipName(title);
    document.body.append(link); link.click(); link.remove();
  } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
