"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";

type RecentLearning = { at: string; kind: "quiz" | "review" | "chat"; title: string; course_name: string | null; href: string };
type Overview = { pending_lessons: number; recent_learning: RecentLearning | null };
const labels = { quiz: "课堂小测", review: "知识点复习", chat: "问答" };

export default function HomeOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    setLoading(true);
    setError("");
    try { setData(await request<Overview>("/courses/overview")); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  const recent = data?.recent_learning;
  const date = recent ? `${new Date(recent.at).getMonth() + 1}月${new Date(recent.at).getDate()}日` : null;
  const retry = <button className="overview-retry" onClick={() => void load()} title={error}>加载失败，点击重试</button>;
  return <>
    <div className="stat-card">
      <div className="stat-label">待处理课次</div>
      <div className="stat-value">{loading || error ? "—" : <Link className="pending-overview-link" href="/pending-lessons" aria-label={`查看${data?.pending_lessons ?? 0}节待处理课次`}>{data?.pending_lessons}<span aria-hidden="true">↗</span></Link>}</div>
      <div className="stat-note">{loading ? "正在统计…" : error ? retry : data?.pending_lessons === 0 ? "全部课次已完成转写与纪要" : <Link href="/pending-lessons">查看具体课次与处理状态 →</Link>}</div>
    </div>
    <div className="stat-card">
      <div className="stat-label">最近学习</div>
      <div className="stat-value">{loading || error || !recent ? "—" : <Link href={recent.href} title={new Date(recent.at).toLocaleString("zh-CN")}>{date}</Link>}</div>
      <div className="stat-note">{loading ? "正在加载…" : error ? retry : recent ? <Link className="overview-activity" href={recent.href} title={`${recent.course_name ? recent.course_name + " · " : ""}${recent.title}`}>{labels[recent.kind]} · {recent.title} →</Link> : "还没有小测、知识点复习或已完成问答记录"}</div>
    </div>
  </>;
}
