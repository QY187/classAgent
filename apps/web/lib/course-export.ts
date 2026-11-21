import { authorizedResponse } from "./api";

export type ExportContents = { summaries: boolean; knowledge: boolean; quizzes: boolean; transcripts: boolean };
export const defaultExportContents: ExportContents = { summaries: true, knowledge: true, quizzes: true, transcripts: true };
export const exportContentChoices = [
  { key: "summaries", label: "智能纪要", description: "PDF · 保留已保存的手动修改" },
  { key: "knowledge", label: "知识点", description: "PDF · 含内容、掌握状态和来源" },
  { key: "quizzes", label: "小测题目", description: "PDF · 仅题目与选项，不含答案解析" },
  { key: "transcripts", label: "文字记录", description: "PDF · 含说话人和片段起止时间" },
] as const;
export function selectedExportLabels(contents: ExportContents): string[] {
  return exportContentChoices.filter((choice) => contents[choice.key]).map((choice) => choice.label);
}
export type CourseExportOptions = { lesson_ids: string[] | null; contents?: ExportContents };

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

export async function previewCourseExport(courseId: string, options: CourseExportOptions, signal: AbortSignal, document?: string): Promise<string[] | Blob> {
  const query = document === undefined ? "" : `?document=${encodeURIComponent(document)}`;
  const response = await authorizedResponse(`/courses/${encodeURIComponent(courseId)}/export/preview${query}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options), signal,
  });
  if (document === undefined) return (await response.json()).documents;
  if (!response.headers.get("Content-Type")?.startsWith("application/pdf")) throw new Error("未收到可用的PDF，请重试。");
  const blob = await response.blob();
  if (await blob.slice(0, 5).text() !== "%PDF-") throw new Error("PDF文件不完整，请重试。");
  return blob;
}
