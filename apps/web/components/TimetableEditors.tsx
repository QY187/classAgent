"use client";

import { useState, type FormEvent } from "react";
import { errorMessage } from "../lib/api";
import { groupPeriods, patternLabels, weekdays, type Entry, type Period, type Semester } from "../lib/timetable";

type SemesterInput = Pick<Semester, "name" | "start_date" | "week_count" | "periods">;
export type EntryInput = Omit<Entry, "id">;
export type CourseChoice = { id: string; name: string };

export function SemesterEditor({ initial, defaults, onClose, onSave }: {
  initial: Semester | null;
  defaults: Period[];
  onClose: () => void;
  onSave: (input: SemesterInput) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [start, setStart] = useState(initial?.start_date ?? "");
  const [weeks, setWeeks] = useState(String(initial?.week_count ?? 20));
  const [periods, setPeriods] = useState((initial?.periods ?? defaults).map((period) => ({ ...period })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function changePeriod(index: number, field: keyof Period, value: string) {
    setPeriods((current) => current.map((period, row) => row === index ? { ...period, [field]: value } : period));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!name.trim()) { setError("请输入学期名称"); return; }
    if (periods.some((period, index) => period.start >= period.end || (index > 0 && period.start < periods[index - 1].end))) {
      setError("请按时间顺序填写节次，结束时间应晚于开始时间，各节之间不能重叠");
      return;
    }
    setBusy(true); setError("");
    try { await onSave({ name: name.trim(), start_date: start, week_count: Number(weeks), periods }); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop">
    <form className="modal timetable-editor" role="dialog" aria-modal="true" aria-label={initial ? "编辑学期" : "新建学期"} onSubmit={submit}>
      <h2>{initial ? "编辑学期与节次" : "设置一个新学期"}</h2>
      <p className="timetable-help">起始日及之后 6 天为第 1 周，每 7 天进入下一周。通常选择开学那一周的周一。</p>
      {initial && <p className="timetable-help">更改起始日期会重新计算已有课程的周次。</p>}
      {error && <p className="notice" role="alert">{error}</p>}
      <fieldset disabled={busy} className="timetable-fields">
        <label className="field-label">学期名称<input className="field" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} required placeholder="例如：2026年秋季" autoFocus /></label>
        <div className="timetable-form-row">
          <label className="field-label">第1周起始日期<input className="field" type="date" min="1900-01-01" max="2199-12-31" value={start} onChange={(event) => setStart(event.target.value)} required /></label>
          <label className="field-label">学期周数<input className="field" type="number" min={1} max={52} value={weeks} onChange={(event) => setWeeks(event.target.value)} required /></label>
        </div>
        <details className="timetable-period-settings">
          <summary>编辑每天的节次时间（{groupPeriods(periods).length} 大节 / {periods.length} 小节）</summary>
          <p className="timetable-help">每小节之间休息 5 分钟时归为同一大节。默认五个大节分别含 3、2、2、3、3 小节。</p>
          {periods.map((period, index) => <div className="timetable-period-input" key={index}>
            <span>第 {index + 1} 小节</span>
            <input className="field" type="time" aria-label={`第${index + 1}小节开始时间`} value={period.start} onChange={(event) => changePeriod(index, "start", event.target.value)} required />
            <span>至</span>
            <input className="field" type="time" aria-label={`第${index + 1}小节结束时间`} value={period.end} onChange={(event) => changePeriod(index, "end", event.target.value)} required />
          </div>)}
          <div className="timetable-navigation">
            <button className="button button-secondary" type="button" disabled={periods.length >= 20} onClick={() => setPeriods((current) => [...current, { start: current.at(-1)?.end ?? "", end: "" }])}>增加一小节</button>
            <button className="button button-secondary" type="button" disabled={periods.length <= 1} onClick={() => setPeriods((current) => current.slice(0, -1))}>减少最后一小节</button>
          </div>
        </details>
      </fieldset>
      <div className="modal-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? "保存中…" : "保存学期"}</button></div>
    </form>
  </div>;
}

export function EntryEditor({ initial, semester, courses, onClose, onSave, onDelete }: {
  initial: Entry | null;
  semester: Semester;
  courses: CourseChoice[];
  onClose: () => void;
  onSave: (input: EntryInput) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const groups = groupPeriods(semester.periods);
  const [draft, setDraft] = useState<EntryInput>(initial ?? {
    title: "", course_id: null, room: "", teacher: "", weekday: 1,
    start_period: 1, end_period: groups[0]?.end_period ?? 1,
    start_week: 1, end_week: semester.week_count, week_pattern: "all", color: "teal",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function number(field: "weekday" | "start_period" | "end_period" | "start_week" | "end_week", value: string) {
    setDraft((current) => ({ ...current, [field]: Number(value) }));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!draft.title.trim()) { setError("请输入课程名称"); return; }
    if (draft.end_week < draft.start_week || draft.end_period < draft.start_period) {
      setError("结束周次和结束节次应不小于开始值"); return;
    }
    if (draft.start_week === draft.end_week && draft.week_pattern !== "all" &&
        draft.start_week % 2 !== (draft.week_pattern === "odd" ? 1 : 0)) {
      setError("所选周次与单双周设置不一致"); return;
    }
    setBusy(true); setError("");
    try {
      // 编辑对象包含 id，只发送可编辑字段。
      const { title, course_id, room, teacher, weekday, start_period, end_period, start_week, end_week, week_pattern, color } = draft;
      await onSave({ title: title.trim(), course_id, room, teacher, weekday, start_period, end_period, start_week, end_week, week_pattern, color });
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (busy || !window.confirm(`删除「${draft.title}」的这条排课？`)) return;
    setBusy(true); setError("");
    try { await onDelete(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop">
    <form className="modal timetable-editor" role="dialog" aria-modal="true" aria-label={initial ? "编辑排课" : "添加课程安排"} onSubmit={submit}>
      <h2>{initial ? "编辑课程安排" : "添加课程安排"}</h2>
      {error && <p className="notice" role="alert">{error}</p>}
      <fieldset disabled={busy} className="timetable-fields">
        <label className="field-label">关联课程（可选）<select className="field" value={draft.course_id ?? ""} onChange={(event) => {
          const course = courses.find((item) => item.id === event.target.value);
          setDraft((current) => ({ ...current, course_id: course?.id ?? null, title: course ? course.name.slice(0, 100) : current.title }));
        }}><option value="">自行填写课程名称</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}</select></label>
        <label className="field-label">课程名称<input className="field" required maxLength={100} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} autoFocus /></label>
        <div className="timetable-form-row">
          <label className="field-label">教室<input className="field" maxLength={100} value={draft.room} onChange={(event) => setDraft({ ...draft, room: event.target.value })} /></label>
          <label className="field-label">教师<input className="field" maxLength={100} value={draft.teacher} onChange={(event) => setDraft({ ...draft, teacher: event.target.value })} /></label>
        </div>
        <div className="timetable-form-row">
          <label className="field-label">星期<select className="field" value={draft.weekday} onChange={(event) => number("weekday", event.target.value)}>{[1, 2, 3, 4, 5, 6, 7].map((day) => <option key={day} value={day}>{weekdays[day % 7]}</option>)}</select></label>
          <label className="field-label">上课频率<select className="field" value={draft.week_pattern} onChange={(event) => setDraft({ ...draft, week_pattern: event.target.value as Entry["week_pattern"] })}>{Object.entries(patternLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        <label className="field-label">按大节选择时间<select className="field" value={groups.findIndex((group) => group.start_period === draft.start_period && group.end_period === draft.end_period)} onChange={(event) => {
          const group = groups[Number(event.target.value)];
          if (group) setDraft((current) => ({ ...current, start_period: group.start_period, end_period: group.end_period }));
        }}><option value={-1} disabled>自定义小节范围（使用下方设置）</option>{groups.map((group, index) => <option key={group.start_period} value={index}>第{index + 1}大节 · {group.start}—{group.end}（第{group.start_period}—{group.end_period}小节）</option>)}</select></label>
        <div className="timetable-form-row">
          <label className="field-label">开始小节<select className="field" value={draft.start_period} onChange={(event) => number("start_period", event.target.value)}>{semester.periods.map((period, index) => <option key={index} value={index + 1}>第{index + 1}小节 · {period.start}</option>)}</select></label>
          <label className="field-label">结束小节<select className="field" value={draft.end_period} onChange={(event) => number("end_period", event.target.value)}>{semester.periods.map((period, index) => <option key={index} value={index + 1}>第{index + 1}小节 · {period.end}</option>)}</select></label>
        </div>
        <div className="timetable-form-row">
          <label className="field-label">开始周次<input className="field" required type="number" min={1} max={semester.week_count} value={draft.start_week || ""} onChange={(event) => number("start_week", event.target.value)} /></label>
          <label className="field-label">结束周次<input className="field" required type="number" min={1} max={semester.week_count} value={draft.end_week || ""} onChange={(event) => number("end_week", event.target.value)} /></label>
        </div>
        <p className="timetable-help">颜色按课程自动分配，同一门课在整个学期保持同色。手动录入时请使用一致的课程名称，或关联同一门课程。</p>
      </fieldset>
      <div className="modal-actions">
        {initial && <button type="button" className="button button-quiet" disabled={busy} onClick={remove}>删除排课</button>}
        <button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button>
        <button className="button button-primary" type="submit" disabled={busy}>{busy ? "保存中…" : "保存排课"}</button>
      </div>
    </form>
  </div>;
}
