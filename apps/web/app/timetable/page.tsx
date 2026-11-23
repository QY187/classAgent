"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import { patternLabels, weekdays, type Entry, type Period, type Semester, type WeekView } from "../../lib/timetable";
import TimetableBoard from "../../components/TimetableBoard";
import { EntryEditor, SemesterEditor, type CourseChoice } from "../../components/TimetableEditors";
import TimetableImport from "../../components/TimetableImport";

type SemesterList = { items: Semester[]; default_periods: Period[] };

export default function TimetablePage() {
  const [catalog, setCatalog] = useState<SemesterList | null>(null);
  const [courses, setCourses] = useState<CourseChoice[]>([]);
  const [semesterId, setSemesterId] = useState("");
  const [data, setData] = useState<WeekView | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [week, setWeek] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState("");
  const [semesterEditor, setSemesterEditor] = useState<"new" | "edit" | null>(null);
  const [entryEditor, setEntryEditor] = useState<Entry | "new" | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const autoImportOpened = useRef(false);
  const semester = catalog?.items.find((item) => item.id === semesterId) ?? null;

  const loadCatalog = useCallback(async (preferred?: string) => {
    const result = await request<SemesterList>("/timetable/semesters");
    setCatalog(result);
    setSemesterId((current) => {
      const selected = preferred ?? current;
      return result.items.some((item) => item.id === selected) ? selected : (result.items.find((item) => item.is_active) ?? result.items[0])?.id ?? "";
    });
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([loadCatalog(), request<CourseChoice[]>("/courses")])
      .then(([, items]) => { if (active) setCourses(items); })
      .catch((cause) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [loadCatalog]);

  useEffect(() => {
    if (!semesterId) { setBusy(false); setData(null); setEntries([]); return; }
    const controller = new AbortController();
    setBusy(true); setError(""); setData(null); setEntries([]);
    const query = new URLSearchParams({ semester_id: semesterId });
    if (week !== null) query.set("week", String(week));
    Promise.all([
      request<WeekView>(`/timetable/week?${query}`, { signal: controller.signal }),
      request<Entry[]>(`/timetable/semesters/${semesterId}/entries`, { signal: controller.signal }),
    ]).then(([view, items]) => {
      if (!controller.signal.aborted) { setData(view); setEntries(items); }
    }).catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [semesterId, week, revision]);

  useEffect(() => {
    if (!busy && semesterId && !autoImportOpened.current && new URLSearchParams(window.location.search).get("import") === "1") {
      autoImportOpened.current = true;
      setImportOpen(true);
    }
  }, [busy, semesterId]);

  function changeWeek(value: number | null) {
    setWeek(value);
    setRevision((current) => current + 1);
  }
  async function refresh() {
    setActionBusy(true); setError("");
    try {
      const [, items] = await Promise.all([loadCatalog(), request<CourseChoice[]>("/courses")]);
      setCourses(items);
      setRevision((current) => current + 1);
    }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setActionBusy(false); }
  }
  async function activate() {
    setActionBusy(true); setError("");
    try {
      await request(`/timetable/semesters/${semesterId}/activate`, { method: "POST" });
      await loadCatalog();
      setRevision((current) => current + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setActionBusy(false); }
  }
  async function removeSemester() {
    if (!semester || !window.confirm(`删除「${semester.name}」及其全部排课？`)) return;
    setActionBusy(true); setError("");
    try {
      await request(`/timetable/semesters/${semesterId}`, { method: "DELETE" });
      setWeek(null);
      await loadCatalog("");
      setRevision((current) => current + 1);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setActionBusy(false); }
  }

  return <main className="content timetable-page">
    <section className="page-hero page-hero-compact"><div className="page-hero-copy"><h1>我的课程表</h1><p>按学期起始日期计算周次，设置好后，首页会自动展示本周课程。</p></div><div className="page-hero-actions"><button className="button button-primary" disabled={!catalog || actionBusy} onClick={() => setSemesterEditor("new")}>新建学期</button></div></section>
    {error && <div className="notice" role="alert">{error}<button className="button button-quiet" onClick={refresh} disabled={actionBusy}>重新加载</button></div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    {!catalog && !error && <p role="status">正在读取课程表…</p>}
    {catalog && catalog.items.length === 0 && <section className="panel timetable-empty"><div><h2>从开学日期开始</h2><p>例如设置 2026 年秋季，起始日为 8 月 24 日，11 月 23 日这一周就是第 14 周。</p></div><button className="button button-primary" onClick={() => setSemesterEditor("new")}>设置学期与节次</button></section>}
    {semester && <>
      <section className="panel timetable-management">
        <label className="field-label">查看学期<select className="field" value={semesterId} disabled={busy || actionBusy} onChange={(event) => { setSemesterId(event.target.value); setWeek(null); setEntryEditor(null); }}>
          {catalog?.items.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_active ? "（首页学期）" : ""}</option>)}
        </select></label>
        <div className="timetable-navigation">
          {!semester.is_active && <button className="button button-secondary" disabled={actionBusy} onClick={activate}>设为首页学期</button>}
          <button className="button button-secondary" disabled={busy || actionBusy} onClick={() => setSemesterEditor("edit")}>编辑学期与节次</button>
          <button className="button button-secondary" disabled={busy || actionBusy || Boolean(error)} onClick={() => setImportOpen(true)}>导入解析</button>
          <button className="button button-primary" disabled={busy || actionBusy} onClick={() => setEntryEditor("new")}>添加排课</button>
          <button className="button button-quiet" disabled={actionBusy} onClick={removeSemester}>删除学期</button>
        </div>
      </section>
      {busy && <p role="status">正在更新课表…</p>}
      {data?.semester?.id === semesterId && !error && <TimetableBoard data={data} busy={busy || actionBusy} onWeek={changeWeek} onEdit={setEntryEditor} />}
      <section className="panel timetable-entry-list">
        <div className="panel-header"><h2>本学期全部排课</h2><span>{busy ? "读取中…" : `${entries.length} 条`}</span></div>
        {busy ? <p className="timetable-help">正在读取排课…</p> : error ? <p className="timetable-help">读取未完成，请重新加载。</p> : entries.length === 0 ? <p className="timetable-help">尚未添加排课。你可以关联课程库里的课程，也可以自行填写名称。</p> : entries.map((entry) => <button key={entry.id} className="timetable-entry-row" disabled={busy || actionBusy} onClick={() => setEntryEditor(entry)}>
          <strong>{entry.title}</strong><span>{weekdays[entry.weekday % 7]} · 第 {entry.start_period}—{entry.end_period} 小节 · 第 {entry.start_week}—{entry.end_week} 周 · {patternLabels[entry.week_pattern]}{entry.room ? " · " + entry.room : ""}</span><span>编辑</span>
        </button>)}
      </section>
    </>}
    {semesterEditor && catalog && <SemesterEditor key={semesterEditor + semesterId} initial={semesterEditor === "edit" ? semester : null} defaults={catalog.default_periods} onClose={() => setSemesterEditor(null)} onSave={async (input) => {
      const saved = await request<Semester>(semesterEditor === "edit" ? `/timetable/semesters/${semesterId}` : "/timetable/semesters", { method: semesterEditor === "edit" ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
      setWeek(null);
      await loadCatalog(saved.id);
      setRevision((current) => current + 1);
      setSemesterEditor(null);
    }} />}
    {entryEditor && semester && <EntryEditor key={entryEditor === "new" ? "new" : entryEditor.id} initial={entryEditor === "new" ? null : entryEditor} semester={semester} courses={courses} onClose={() => setEntryEditor(null)} onSave={async (input) => {
      const path = `/timetable/semesters/${semesterId}/entries`;
      await request(entryEditor === "new" ? path : `${path}/${entryEditor.id}`, { method: entryEditor === "new" ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
      setRevision((current) => current + 1);
      setEntryEditor(null);
    }} onDelete={async () => {
      if (entryEditor === "new") return;
      await request(`/timetable/semesters/${semesterId}/entries/${entryEditor.id}`, { method: "DELETE" });
      setRevision((current) => current + 1);
      setEntryEditor(null);
    }} />}
    {importOpen && semester && <TimetableImport semester={semester} existing={entries} onClose={() => setImportOpen(false)} onImported={(result) => {
      setNotice(`导入完成：新增 ${result.added} 条排课，跳过 ${result.skipped} 条重复记录。`);
      setImportOpen(false);
      setRevision((current) => current + 1);
    }} />}
  </main>;
}
