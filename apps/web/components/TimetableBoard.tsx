"use client";

import Link from "next/link";
import { calendarDate, groupPeriods, overlappingEntries, weekdays, type Entry, type WeekView } from "../lib/timetable";
import TimetableCourseStack from "./TimetableCourseStack";
import "./timetable.css";

export default function TimetableBoard({ data, busy, onWeek, onEdit, compact = false }: {
  data: WeekView;
  busy: boolean;
  onWeek: (week: number | null) => void;
  onEdit?: (entry: Entry) => void;
  compact?: boolean;
}) {
  const semester = data.semester;
  if (!semester || data.week === null) return null;
  const groups = groupPeriods(semester.periods);
  const semesterTitle = semester.name.replace(/(春季|秋季|夏季|冬季)(?!学期)/u, "$1学期");
  const month = Number(data.days[0].slice(5, 7));
  return <section className={`panel timetable-panel${compact ? " is-compact" : ""}`} aria-label="每周课程表">
    <div className={`timetable-heading${compact ? " has-actions" : ""}`}>
      <div className="timetable-header-main">
      <h2 className="timetable-semester-title">{semesterTitle}</h2>
      <div className="timetable-week-navigation">
        <button type="button" className="timetable-week-arrow" aria-label="上一周" title="上一周" disabled={busy || data.week <= 1} onClick={() => onWeek(data.week! - 1)}>‹</button>
        <select className="timetable-week-select" aria-label="选择周次" value={data.week} disabled={busy} onChange={(event) => onWeek(Number(event.target.value))}>
          {Array.from({ length: semester.week_count }, (_, index) => <option key={index + 1} value={index + 1}>第 {index + 1} 周{index + 1 === data.current_week ? "（本周）" : ""}</option>)}
        </select>
        <button type="button" className="timetable-week-arrow" aria-label="下一周" title="下一周" disabled={busy || data.week >= semester.week_count} onClick={() => onWeek(data.week! + 1)}>›</button>
      </div>
      <button type="button" className="timetable-return-current" disabled={busy || data.week === data.current_week} onClick={() => onWeek(null)}>回到本周</button>
      </div>
      {compact && <nav className="timetable-header-actions" aria-label="课表操作"><Link href="/timetable?import=1">导入课表</Link><Link href="/timetable">编辑课表</Link></nav>}
    </div>
    {data.status === "before" && <p className="timetable-state" role="status">学期尚未开始，当前展示第 {data.week} 周。</p>}
    {data.status === "after" && <p className="timetable-state" role="status">本学期已结束，当前展示第 {data.week} 周。</p>}
    <div className="timetable-scroll" aria-label="整周课表总览">
      <div className="timetable-grid" style={{
        gridTemplateRows: `64px ${groups.map((group) => `${(group.end_period - group.start_period + 1) * (compact ? 48 : 52)}px`).join(" ")}`,
      }}>
        <div className="timetable-corner" style={{ gridColumn: 1, gridRow: 1 }}>{month}月</div>
        {data.days.map((day, index) => <div key={day}
          className={`timetable-day${day === data.today ? " is-today" : ""}`}
          aria-label={`${day} ${weekdays[calendarDate(day).getUTCDay()]}${day === data.today ? " 今天" : ""}`}
          style={{ gridColumn: index + 2, gridRow: 1 }}>
          <strong>{index > 0 && day.slice(5, 7) !== data.days[index - 1].slice(5, 7) ? `${Number(day.slice(5, 7))}/${Number(day.slice(8))}` : Number(day.slice(8))}</strong><span>{weekdays[calendarDate(day).getUTCDay()]}</span>{day === data.today && <small className="timetable-today-badge">今日</small>}
        </div>)}
        {groups.map((group, index) => <div className="timetable-block" key={group.start_period}
          aria-label={`第${index + 1}大节 ${group.start}—${group.end}`}
          title={`第${index + 1}大节：${group.start}—${group.end}`}
          style={{ gridColumn: 1, gridRow: index + 2, gridTemplateRows: `repeat(${group.end_period - group.start_period + 1}, minmax(0, 1fr))` }}>
          {semester.periods.slice(group.start_period - 1, group.end_period).map((period, offset) => <div className="timetable-small-period" key={offset}><strong>{group.start_period + offset}</strong><span>{period.start}</span></div>)}
        </div>)}
        {groups.flatMap((group, row) => data.days.map((day, column) => {
          const weekday = ((calendarDate(day).getUTCDay() + 6) % 7) + 1;
          const entries = data.entries.filter((entry) => !entry.is_all_day && entry.weekday === weekday &&
            entry.start_period <= group.end_period && entry.end_period >= group.start_period)
            .sort((left, right) => left.start_period - right.start_period);
          return <div key={`${row}-${day}`} className={`timetable-cell${day === data.today ? " is-today" : ""}`}
            style={{ gridColumn: column + 2, gridRow: row + 2, gridTemplateRows: `repeat(${group.end_period - group.start_period + 1}, minmax(0, 1fr))` }}>
            {overlappingEntries(entries).map((cluster) => {
              const start = Math.max(group.start_period, Math.min(...cluster.map((entry) => entry.start_period)));
              const end = Math.min(group.end_period, Math.max(...cluster.map((entry) => entry.end_period)));
              return <TimetableCourseStack key={`${data.week}-${cluster.map((entry) => entry.id).join("-")}`} entries={cluster} semester={semester} busy={busy} onEdit={onEdit} compact={compact} start={start} end={end} style={{ gridColumn: 1, gridRow: `${start - group.start_period + 1} / span ${end - start + 1}` }} />;
            })}
          </div>;
        }))}
        {data.days.map((day, column) => {
          const weekday = ((calendarDate(day).getUTCDay() + 6) % 7) + 1;
          const activities = data.entries.filter((entry) => entry.is_all_day && entry.weekday === weekday)
            .sort((left, right) => left.title.localeCompare(right.title, "zh-CN") || left.start_period - right.start_period);
          if (!activities.length) return null;
          return <div key={`all-day-${day}`} className="timetable-all-day-lane" style={{ gridColumn: column + 2, gridRow: `2 / span ${groups.length}`, gridTemplateRows: `repeat(${semester.periods.length}, minmax(0, 1fr))`, gridTemplateColumns: "minmax(0, 1fr)" }}>
            {overlappingEntries(activities).map((cluster) => {
              const start = Math.min(...cluster.map((entry) => entry.start_period));
              const end = Math.max(...cluster.map((entry) => entry.end_period));
              return <TimetableCourseStack key={`${data.week}-${cluster.map((entry) => entry.id).join("-")}`} entries={cluster} semester={semester} busy={busy} onEdit={onEdit} compact={compact} start={start} end={end} style={{ gridColumn: 1, gridRow: `${start} / ${end + 1}` }} />;
            })}
          </div>;
        })}
      </div>
      {data.entries.length === 0 && <div className="timetable-empty-week" role="status"><span>这一周暂无课程安排</span></div>}
    </div>
  </section>;
}
