"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";
import { calendarDate, weekdays, type WeekView } from "../lib/timetable";

export default function HomeToday() {
  const [data, setData] = useState<WeekView | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [clock, setClock] = useState("");
  useEffect(() => {
    const update = () => { if (!document.hidden) setRefresh((value) => value + 1); };
    const timer = window.setInterval(update, 60000);
    window.addEventListener("focus", update); document.addEventListener("visibilitychange", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); document.removeEventListener("visibilitychange", update); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setClock(new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date()));
    request<WeekView>("/timetable/week", { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setData(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); });
    return () => controller.abort();
  }, [refresh]);
  const day = data ? ((calendarDate(data.today).getUTCDay() + 6) % 7) + 1 : 0;
  const entries = data?.status === "current" ? data.entries.filter((entry) => entry.weekday === day).sort((left, right) => left.start_period - right.start_period) : [];
  return <section className="panel home-today" aria-label="今日课程">
    <div className="home-widget-heading"><h2>今日课程</h2><span>{data ? `${data.today.slice(5).replace("-", "/")} · ${weekdays[day % 7]}` : ""}</span></div>
    {error ? <div className="home-widget-empty" role="alert">{error}<button className="button button-quiet" onClick={() => setRefresh((value) => value + 1)}>重试</button></div> : !data ? <p className="home-widget-empty" role="status">正在读取今日安排…</p> : !data.semester ? <div className="home-widget-empty">设置学期后，这里会显示每天的课程。<Link href="/timetable">设置课表 →</Link></div> : entries.length === 0 ? <div className="home-widget-empty"><strong>{data.status === "current" ? "今天没有课程安排" : "当前不在上课周内"}</strong><p>可以复习知识点，或整理已有课堂资料。</p><Link href="/review">去复习 →</Link></div> : <div className="home-today-list">{entries.slice(0, 3).map((entry) => {
      const start = data.semester!.periods[entry.start_period - 1].start;
      const end = data.semester!.periods[entry.end_period - 1].end;
      const status = clock < start ? "未开始" : clock >= end ? "已结束" : "进行中";
      return <Link className="home-today-entry" href="/timetable" key={entry.id}><span className="home-today-time">{start}<small>{end}</small></span><span className="home-today-copy"><strong>{entry.title}</strong><small>{entry.room || "教室未填写"}{entry.teacher ? ` · ${entry.teacher}` : ""}</small></span><span className={`home-today-status${status === "进行中" ? " is-current" : ""}`}>{status}</span></Link>;
    })}{entries.length > 3 && <Link className="home-today-more" href="/timetable">还有 {entries.length - 3} 条安排，查看全部 →</Link>}</div>}
  </section>;
}
