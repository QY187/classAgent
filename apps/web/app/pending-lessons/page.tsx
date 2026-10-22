"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import "./pending.css";

type PendingLesson = { id: string; title: string; course_name: string; lesson_date: string | null; state: string; stage_label: string; error_message: string | null; href: string };
type PendingPage = { total: number; items: PendingLesson[]; has_more: boolean };
const PAGE_SIZE = 20;

export default function PendingLessons() {
  const [page, setPage] = useState<PendingPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    request<PendingPage>(`/courses/pending-lessons?offset=${offset}&limit=${PAGE_SIZE}`)
      .then((result) => { if (active) {
        if (!result.items.length && offset > 0) { setOffset(Math.max(0, Math.floor((result.total - 1) / PAGE_SIZE) * PAGE_SIZE)); }
        else { setPage(result); }
      } })
      .catch((cause) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [offset, refresh]);
  return <main className="content pending-page">
    <section className="page-hero page-hero-compact">
      <span className="page-hero-icon" aria-hidden="true">◷</span>
      <div className="page-hero-copy"><div className="eyebrow">资料处理</div><h1>待处理课次</h1><p>查看未完成转写或纪要的课次，进入课次继续处理。</p></div>
      <div className="page-hero-actions"><button className="button button-secondary" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>刷新状态</button><Link className="button button-secondary" href="/">返回课程库</Link></div>
    </section>
    {error ? <div className="notice" role="alert">{error} <button className="overview-retry" onClick={() => setRefresh((value) => value + 1)}>重新加载</button></div>
      : loading ? <div className="empty-state" role="status">正在加载待处理课次…</div>
      : page && page.total === 0 ? <div className="empty-state"><strong>没有待处理课次</strong><p>当前课次的转写与纪要均已完成。</p><Link className="button button-secondary" href="/">返回课程库</Link></div>
      : page && <>
        <div className="section-head"><h2>共 {page.total} 节待处理课次</h2><span>状态以最近一次处理记录为准</span></div>
        <div className="pending-list">{page.items.map((lesson) => <article className="pending-row" key={lesson.id}>
          <div className="pending-row-heading"><div><div className="pending-course">{lesson.course_name}{lesson.lesson_date ? ` · ${lesson.lesson_date}` : ""}</div><h2>{lesson.title}</h2></div><span className={`pending-badge pending-badge-${lesson.state}`}>{lesson.stage_label}</span></div>
          {lesson.error_message && <div className="pending-error"><strong>失败原因</strong><p>{lesson.error_message}</p></div>}
          <div className="pending-row-footer"><span>{lesson.state === "created" ? "上传录音后开始转写与纪要处理" : lesson.state === "failed" ? "进入课次查看详情并重试" : lesson.state === "stale" ? "课堂文字已变化，请更新纪要" : "进入课次查看处理进度"}</span><Link className="button button-secondary" href={lesson.href}>进入课次 ↗</Link></div>
        </article>)}</div>
        {(offset > 0 || page.has_more) && <nav className="pending-pagination" aria-label="待处理课次分页"><button className="button button-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span><button className="button button-secondary" disabled={!page.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button></nav>}
      </>}
  </main>;
}
