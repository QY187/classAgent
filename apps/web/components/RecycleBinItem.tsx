import type { ReactNode } from "react";
import { recycledKindLabel, type RecycledItem } from "../lib/recycle-bin";

export default function RecycleBinItem({ item, disabled, restoring, onRestore, children }: {
  item: RecycledItem; disabled: boolean; restoring: boolean; onRestore: () => void; children?: ReactNode;
}) {
  return <article className="recycle-item">
    <span className={`recycle-item-icon ${item.kind}`} aria-hidden="true">{item.kind === "course" ? "▦" : item.kind === "lesson" ? "◷" : "▤"}</span>
    <div className="recycle-item-copy"><span className="recycle-kind-label">{recycledKindLabel[item.kind]}</span><h3>{item.title}</h3><p>{item.kind !== "course" && <span>{item.course_name}{item.kind === "material" && item.lesson_title ? ` / ${item.lesson_title}` : ""} · </span>}删除于 {new Date(item.deleted_at).toLocaleString("zh-CN")}</p></div>
    <div className="recycle-item-actions"><button className="button button-secondary" disabled={disabled} onClick={onRestore}>{restoring ? "正在恢复…" : "恢复"}</button>{children}</div>
  </article>;
}
