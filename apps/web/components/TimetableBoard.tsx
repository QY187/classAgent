"use client";

import Link from "next/link";
import { calendarDate, groupPeriods, weekdays, type Entry, type WeekView } from "../lib/timetable";
import { timetableColorStyle } from "../lib/timetable-colors";
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
        <button type="button" className="timetable-week-label" aria-label="回到本周" title="点击回到本周" disabled={busy} onClick={() => onWeek(null)}>第 {data.week} 周</button>
        <button type="button" className="timetable-week-arrow" aria-label="下一周" title="下一周" disabled={busy || data.week >= semester.week_count} onClick={() => onWeek(data.week! + 1)}>›</button>
      </div>
      </div>
      {compact && <nav className="timetable-header-actions" aria-label="课表操作"><Link href="/timetable?import=1">导入课表</Link><Link href="/timetable">编辑课表</Link></nav>}
    </div>
    {data.status === "before" && <p className="timetable-state" role="status">学期尚未开始，当前展示第 {data.week} 周。</p>}
    {data.status === "after" && <p className="timetable-state" role="status">本学期已结束，当前展示第 {data.week} 周。</p>}
    <div className="timetable-scroll" aria-label="整周课表总览">
      <div className="timetable-grid" style={{
        gridTemplateRows: `44px ${groups.map((group) => `${(group.end_period - group.start_period + 1) * (compact ? 30 : 36)}px`).join(" ")}`,
      }}>
        <div className="timetable-corner" style={{ gridColumn: 1, gridRow: 1 }}>{month}月</div>
        {data.days.map((day, index) => <div key={day}
          className={`timetable-day${day === data.today ? " is-today" : ""}`}
          aria-label={`${day} ${weekdays[calendarDate(day).getUTCDay()]}${day === data.today ? " 今天" : ""}`}
          style={{ gridColumn: index + 2, gridRow: 1 }}>
          <strong>{index > 0 && day.slice(5, 7) !== data.days[index - 1].slice(5, 7) ? `${Number(day.slice(5, 7))}/${Number(day.slice(8))}` : Number(day.slice(8))}</strong><span>{weekdays[calendarDate(day).getUTCDay()]}{!compact && day === data.today ? " · 今天" : ""}</span>
        </div>)}
        {groups.map((group, index) => <div className="timetable-block" key={group.start_period}
          aria-label={`第${index + 1}大节 ${group.start}—${group.end}`}
          title={`第${index + 1}大节：${group.start}—${group.end}`}
          style={{ gridColumn: 1, gridRow: index + 2 }}>
          <strong>第{index + 1}大节</strong><span>{group.start}</span><span>— {group.end}</span>
        </div>)}
        {groups.flatMap((group, row) => data.days.map((day, column) => {
          const weekday = ((calendarDate(day).getUTCDay() + 6) % 7) + 1;
          const entries = data.entries.filter((entry) => entry.weekday === weekday &&
            entry.start_period <= group.end_period && entry.end_period >= group.start_period)
            .sort((left, right) => left.start_period - right.start_period);
          return <div key={`${row}-${day}`} className={`timetable-cell${day === data.today ? " is-today" : ""}`}
            style={{ gridColumn: column + 2, gridRow: row + 2, gridTemplateRows: `repeat(${group.end_period - group.start_period + 1}, minmax(0, 1fr))` }}>
            {entries.map((entry) => {
              const start = Math.max(entry.start_period, group.start_period);
              const end = Math.min(entry.end_period, group.end_period);
              const partial = start !== group.start_period || end !== group.end_period;
              const occupiedPeriods = end - start + 1;
              const position = { gridRow: `${start - group.start_period + 1} / span ${occupiedPeriods}`, ...timetableColorStyle(entry.color) };
              const time = `${semester.periods[start - 1].start}—${semester.periods[end - 1].end}`;
              const fullTime = `${semester.periods[entry.start_period - 1].start}—${semester.periods[entry.end_period - 1].end}`;
              const title = `${entry.title} · ${weekdays[entry.weekday % 7]}第${entry.start_period}—${entry.end_period}小节 · ${fullTime}${entry.room ? " · " + entry.room : ""}${entry.teacher ? " · " + entry.teacher : ""}`;
              const body = <><strong>{entry.title}</strong>{entry.room && <span>{entry.room}</span>}{partial && <span className="timetable-entry-time">{time}</span>}{entry.teacher && !compact && <span>{entry.teacher}</span>}</>;
              return onEdit
                ? <button key={entry.id} type="button" className="timetable-entry" style={position} data-period-count={occupiedPeriods} title={title} aria-label={`编辑排课：${title}`} onClick={() => onEdit(entry)} disabled={busy}>{body}</button>
                : <Link key={entry.id} className="timetable-entry" style={position} data-period-count={occupiedPeriods} title={title} aria-label={title} href="/timetable">{body}</Link>;
            })}
          </div>;
        }))}
      </div>
      {data.entries.length === 0 && <div className="timetable-empty-week" role="status"><span>这一周暂无课程安排</span></div>}
    </div>
  </section>;
}
