"use client";
import { useCallback, useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";

export default function PendingFileCleanup() {
  const [pending, setPending] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(() => {
    request<{ pending: number }>("/recycle-bin/file-cleanup").then((result) => { setPending(result.pending); setError(""); }).catch((err) => setError(errorMessage(err)));
  }, []);
  useEffect(() => {
    refresh();
    window.addEventListener("classagent:file-cleanup-updated", refresh);
    return () => window.removeEventListener("classagent:file-cleanup-updated", refresh);
  }, [refresh]);
  async function cleanup() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await request<{ pending: number }>("/recycle-bin/file-cleanup", { method: "POST" });
      setPending(result.pending);
      if (result.pending) setError("仍有文件尚未清理完成，可稍后再次重试。");
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  if (!pending && !error) return null;
  return <section className="panel recycle-cleanup"><div><h2>文件清理</h2><p>{pending ? `${pending} 个已彻底删除的文件等待清理。它们不会出现在课程中，也不能恢复。` : "无法读取文件清理状态。"}</p>{error && <p role="alert">{error}</p>}</div><button className="button button-secondary" disabled={busy} onClick={pending ? cleanup : refresh}>{busy ? "正在清理…" : pending ? "重试文件清理" : "重新加载"}</button></section>;
}
