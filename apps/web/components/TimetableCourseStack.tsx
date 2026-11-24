"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { weekdays, type Entry, type Semester } from "../lib/timetable";
import { timetableColorStyle } from "../lib/timetable-colors";

export default function TimetableCourseStack({ entries, semester, busy, onEdit, compact, start, end, style }: {
  entries: Entry[]; semester: Semester; busy: boolean; onEdit?: (entry: Entry) => void;
  compact: boolean; start: number; end: number; style: CSSProperties;
}) {
  const [selected, setSelected] = useState(entries.at(-1)!.id);
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const active = entries.find((entry) => entry.id === selected) ?? entries.at(-1)!;
  const multiple = entries.length > 1;
  const ordered = [...entries.filter((entry) => entry.id !== active.id), active];
  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  function close() { dialog.current?.close(); setOpen(false); trigger.current?.focus(); }
  function description(entry: Entry) {
    return `${entry.title} · ${weekdays[entry.weekday % 7]}${entry.is_all_day ? "全天实践" : ""} · 第${entry.start_period}—${entry.end_period}小节 · ${semester.periods[entry.start_period - 1].start}—${semester.periods[entry.end_period - 1].end}${entry.room ? " · " + entry.room : ""}${entry.teacher ? " · " + entry.teacher : ""}`;
  }
  return <div className={`timetable-course-stack${multiple ? " has-multiple" : ""}`} style={{ ...style, gridTemplateRows: `repeat(${end - start + 1}, minmax(0, 1fr))` }}>
    {ordered.map((entry, index) => {
      const front = entry.id === active.id;
      const depth = Math.min(ordered.length - index - 1, 2);
      const occupied = Math.min(end, entry.end_period) - Math.max(start, entry.start_period) + 1;
      const position: CSSProperties = { ...timetableColorStyle(entry.color), gridRow: `${Math.max(start, entry.start_period) - start + 1} / span ${occupied}`, gridColumn: 1, zIndex: front ? 3 : 2 - depth,
        ...(multiple ? { marginLeft: `${(2 - depth) * 4}px`, marginTop: `${(2 - depth) * 5}px`, marginRight: `${depth * 4}px`, marginBottom: `${depth * 5}px` } : {}) };
      const body = <>{multiple && <span className="timetable-stack-count">{entries.length} 门</span>}<strong>{entry.title}</strong>{entry.is_all_day
        ? <span className="timetable-all-day-caption">全天实践<br/>第{entry.start_period}—{entry.end_period}小节</span>
        : <>{entry.room && <span>{entry.room}</span>}{(entry.start_period > start || entry.end_period < end) && <span className="timetable-entry-time">{semester.periods[entry.start_period - 1].start}—{semester.periods[entry.end_period - 1].end}</span>}{!compact && entry.teacher && <span>{entry.teacher}</span>}</>}</>;
      const className = `timetable-entry${entry.is_all_day ? " timetable-all-day-entry" : ""}`;
      if (!front) return <div key={entry.id} className={`${className} timetable-stack-back`} aria-hidden="true" style={position} />;
      return multiple || onEdit
        ? <button ref={trigger} key={entry.id} type="button" className={className} style={position} data-period-count={occupied} disabled={busy}
          aria-label={multiple ? `查看同一时段的${entries.length}门课程：${entries.map((item) => item.title).join("、")}` : `编辑排课：${description(entry)}`} title={description(entry)}
          onClick={() => multiple ? setOpen(true) : onEdit?.(entry)}>{body}</button>
        : <Link key={entry.id} className={className} style={position} data-period-count={occupied} title={description(entry)} href="/timetable">{body}</Link>;
    })}
    {open && createPortal(<dialog ref={dialog} className="timetable-stack-dialog" aria-label="同一时段的课程" onCancel={(event) => { event.preventDefault(); close(); }}>
      <div className="timetable-stack-dialog-heading"><h2>同一时段的课程</h2><button type="button" className="button button-secondary" onClick={close}>关闭</button></div>
      <p>共 {entries.length} 门课程，选择一门显示在最前方。</p>
      <div className="timetable-stack-options">{entries.map((entry) => <div key={entry.id} className="timetable-stack-option" style={timetableColorStyle(entry.color) as CSSProperties}>
        <strong>{entry.title}</strong><span>{description(entry).slice(entry.title.length + 3)}</span>
        <div><button type="button" className="button button-secondary" onClick={() => { setSelected(entry.id); close(); }}>{entry.id === active.id ? "当前显示" : "展示此课程"}</button>
          {onEdit ? <button type="button" className="button button-primary" onClick={() => { close(); onEdit(entry); }}>编辑排课</button> : <Link className="button button-primary" href="/timetable">编辑课表</Link>}</div>
      </div>)}</div>
    </dialog>, document.body)}
  </div>;
}
