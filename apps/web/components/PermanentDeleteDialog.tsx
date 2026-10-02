"use client";
import { useEffect, useRef, useState } from "react";
import { recycledKindLabel, type RecycledItem } from "../lib/recycle-bin";

export default function PermanentDeleteDialog({ item, busy, error, onCancel, onConfirm }: {
  item: RecycledItem; busy: boolean; error: string; onCancel: () => void; onConfirm: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => { previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="purge-title" aria-describedby="purge-impact" onKeyDown={(event) => {
    if (event.key === "Escape" && !busy) onCancel();
    if (event.key === "Tab") {
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)'));
      const first = controls[0], last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}><h2 id="purge-title">彻底删除{recycledKindLabel[item.kind]}</h2><p>「<strong className="material-delete-filename">{item.title}</strong>」</p><p className="delete-impact" id="purge-impact">{item.kind === "material" ? "此资料的记录和原文件将被永久删除。" : "此内容及其录音、文字记录、纪要、知识点、小测和资料将被永久删除，也包括其中已单独进入回收站的内容。"}此操作无法恢复。</p><label className="purge-acknowledgement"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认不再需要这些内容，了解删除后无法恢复</span></label>{error && <p className="notice" role="alert">{error}</p>}<div className="modal-actions"><button className="button button-secondary" ref={cancelRef} disabled={busy} onClick={onCancel}>取消</button><button className="button button-danger" disabled={!confirmed || busy} onClick={onConfirm}>{busy ? "正在彻底删除…" : "确认彻底删除"}</button></div></div></div>;
}
