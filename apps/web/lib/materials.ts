export type Material = { id: string; course_id: string; lesson_id: string | null; filename: string; size_bytes: number; created_at: string; status: string; processing_status: string; processing_error: string | null; indexed: boolean };
export type MaterialChunk = { chunk_id: string; material_id: string; course_id: string; lesson_id: string | null; filename: string; version: string; position: number; locator_type: "page" | "slide" | "paragraph"; locator_number: number; locator_label: string; text: string; source_type: "material" };
export type MaterialContent = { material: Material; source_status: "current" | "changed"; items: MaterialChunk[]; next_offset: number | null };

export const processingLabels: Record<string, string> = { stored: "未加入问答", queued: "等待解析", processing: "正在解析", indexing: "正在建立索引", ready: "可用于问答", failed: "解析失败", unsupported: "仅预览与下载" };
export function materialHref(item: { course_id: string; material_id: string; position?: number; version?: string }) {
  const params = new URLSearchParams();
  if (item.position !== undefined) params.set("position", String(item.position));
  if (item.version) params.set("version", item.version);
  return `/courses/${encodeURIComponent(item.course_id)}/materials/${encodeURIComponent(item.material_id)}${params.size ? `?${params}` : ""}`;
}
