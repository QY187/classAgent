"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import RecycleBinItem from "../../components/RecycleBinItem";
import RecycleBinPurge from "../../components/RecycleBinPurge";
import PendingFileCleanup from "../../components/PendingFileCleanup";
import { errorMessage, request } from "../../lib/api";
import { recycledKey, recycledKindLabel, type RecycledItem, type RecycledKind } from "../../lib/recycle-bin";

export default function RecycleBinPage() {
  const [items, setItems] = useState<RecycledItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [kind, setKind] = useState<RecycledKind | "all">("all");
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true); setLoadError("");
    try { setItems(await request<RecycledItem[]>("/recycle-bin")); }
    catch (err) { setLoadError(errorMessage(err)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function restore(item: RecycledItem) {
    if (busyKey) return;
    setBusyKey(`restore:${recycledKey(item)}`); setActionError(""); setMessage("");
    try {
      await request(`/recycle-bin/${recycledKey(item)}/restore`, { method: "POST" });
      setItems((current) => current.filter((entry) => recycledKey(entry) !== recycledKey(item)));
      setMessage(`已恢复「${item.title}」，可以回到课程中查看。`);
      window.dispatchEvent(new Event("classagent:courses-updated"));
      await refresh();
    } catch (err) { setActionError(errorMessage(err)); await refresh(); }
    finally { setBusyKey(null); }
  }

  const needle = query.trim().toLocaleLowerCase();
  const visible = items.filter((item) => (kind === "all" || item.kind === kind) && `${item.title} ${item.course_name} ${item.lesson_title || ""}`.toLocaleLowerCase().includes(needle));
  return <main className="content recycle-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">↺</span><div className="page-hero-copy"><div className="eyebrow">资料管理</div><h1>回收站</h1><p>找回误删的课程、课次和资料，恢复后回到原来的位置。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href="/">返回课程库</Link></div></section>
    {message && <p className="notice recycle-success" role="status">{message}</p>}
    {actionError && <p className="notice" role="alert">{actionError}</p>}
    <section className="panel"><div className="panel-header"><h2>已删除的内容</h2><span>{loading ? "加载中" : `${items.length} 项`}</span></div><div className="panel-body">
      <div className="recycle-toolbar"><label className="recycle-search">搜索内容<input className="field" type="search" disabled={!!busyKey} placeholder="搜索名称、课程或课次" value={query} onChange={(event) => setQuery(event.target.value)} /></label><div className="review-status-filter" role="group" aria-label="内容类型">{(["all", "course", "lesson", "material"] as const).map((value) => <button type="button" disabled={!!busyKey} key={value} className={kind === value ? "active" : ""} aria-pressed={kind === value} onClick={() => setKind(value)}>{value === "all" ? "全部" : recycledKindLabel[value]} {items.filter((item) => value === "all" || item.kind === value).length}</button>)}</div></div>
      <p className="recycle-help">删除整门课程后，其课次和资料会随课程一起恢复。之前单独删除的内容仍保留在回收站。这里的内容不会自动清空。</p>
      {loading ? <p role="status">正在加载回收站…</p> : loadError ? <div className="empty-state"><strong role="alert">{loadError}</strong><button className="button button-secondary" onClick={refresh}>重新加载</button></div> : visible.length ? <div className="recycle-list">{visible.map((item) => <RecycleBinItem key={recycledKey(item)} item={item} disabled={!!busyKey} restoring={busyKey === `restore:${recycledKey(item)}`} onRestore={() => restore(item)}><RecycleBinPurge item={item} disabled={!!busyKey} onBusyChange={(busy) => setBusyKey(busy ? `purge:${recycledKey(item)}` : null)} onDeleted={async (pending) => {
        setItems((current) => current.filter((entry) => recycledKey(entry) !== recycledKey(item)));
        setActionError(""); setMessage(`已彻底删除「${item.title}」。${pending ? "部分文件等待清理，可在下方重试。" : ""}`);
        window.dispatchEvent(new Event("classagent:courses-updated"));
        await refresh();
      }} /></RecycleBinItem>)}</div> : <div className="empty-state"><strong>{items.length ? "没有符合条件的内容" : "回收站是空的"}</strong><p>{items.length ? "可以切换类型或修改搜索关键词。" : "删除的课程、课次和资料会先保留在这里。"}</p></div>}
    </div></section>
    <PendingFileCleanup />
  </main>;
}
