"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { errorMessage, request } from "../lib/api";
import type { WeekView } from "../lib/timetable";
import TimetableBoard from "./TimetableBoard";

export default function HomeTimetable() {
  const [data, setData] = useState<WeekView | null>(null);
  const [week, setWeek] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    const update = () => { if (!document.hidden) setRefresh((value) => value + 1); };
    const timer = window.setInterval(update, 60000);
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    request<WeekView>("/timetable/week" + (week === null ? "" : `?week=${week}`), { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [week, refresh]);
  function changeWeek(value: number | null) {
    setWeek(value);
    setRefresh((current) => current + 1);
  }
  if (error) return <section className="panel timetable-empty" role="alert">课表读取失败：{error}<button className="button button-secondary" onClick={() => changeWeek(null)}>重新读取本周</button></section>;
  if (!data) return <section className="panel timetable-empty" role="status">正在读取本周课表…</section>;
  if (!data.semester) return <section className="panel timetable-empty"><div><h2>本周课程表</h2><p>设置学期起始日期、节次和课程，首页会自动显示本周安排。</p></div><Link className="button button-primary" href="/timetable">设置我的课表</Link></section>;
  return <TimetableBoard data={data} busy={busy} onWeek={changeWeek} compact />;
}
