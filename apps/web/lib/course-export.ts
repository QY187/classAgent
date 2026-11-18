import { authorizedResponse } from "./api";

export type ExportContents = { summaries: boolean; transcripts: boolean; knowledge: boolean; quizzes: boolean; answers: boolean; audio: boolean; materials: boolean };
export const defaultExportContents: ExportContents = { summaries: true, transcripts: true, knowledge: false, quizzes: false, answers: false, audio: false, materials: false };
export const exportContentChoices = [
  { key: "summaries", label: "智能纪要", description: "Markdown · 保留已保存的手动修改" },
  { key: "transcripts", label: "文字记录", description: "TXT · 含说话人和片段起止时间" },
  { key: "knowledge", label: "知识点", description: "Markdown · 含内容、掌握状态和来源" },
  { key: "quizzes", label: "小测题目", description: "Markdown · 可另选参考答案与解析" },
  { key: "audio", label: "原音频", description: "原始文件 · 资料包可能较大" },
  { key: "materials", label: "上传课件", description: "原始文件 · 包含课程公共课件" },
] as const;
export function selectedExportLabels(contents: ExportContents): string[] {
  return exportContentChoices.filter((choice) => contents[choice.key]).map((choice) => choice.key === "quizzes" && contents.answers ? "小测题目、答案与解析" : choice.label);
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
