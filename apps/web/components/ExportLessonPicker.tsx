"use client";
import { useState } from "react";

type Lesson = { id: string; title: string; lesson_date?: string | null };
export default function ExportLessonPicker({ lessons, selected, onChange, disabled }: { lessons: Lesson[]; selected: string[]; onChange: (ids: string[]) => void; disabled: boolean }) {
  const [query, setQuery] = useState("");
  const matches = lessons.filter((lesson) => `${lesson.title} ${lesson.lesson_date || ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <fieldset className="export-lesson-picker" disabled={disabled}>
    <legend>选择课次 · 已选 {selected.length} 节</legend>
    <div className="export-picker-tools"><input type="search" className="field" aria-label="搜索导出课次" placeholder="搜索标题或日期" value={query} onChange={(event) => setQuery(event.target.value)} /><button type="button" className="button button-secondary" disabled={!matches.length || selected.length >= 500} onClick={() => onChange([...new Set([...selected, ...matches.map((lesson) => lesson.id)])].slice(0, 500))}>{query ? "选中搜索结果" : "选中所有课次"}</button><button type="button" className="button button-quiet" disabled={!selected.length} onClick={() => onChange([])}>清空选择</button></div>
    <div className="export-lesson-list">{matches.map((lesson) => <label key={lesson.id}><input type="checkbox" checked={selected.includes(lesson.id)} disabled={selected.length >= 500 && !selected.includes(lesson.id)} onChange={() => onChange(selected.includes(lesson.id) ? selected.filter((id) => id !== lesson.id) : [...selected, lesson.id])} /><span>{lesson.title}<small>{lesson.lesson_date || "未设置日期"}</small></span></label>)}</div>
    {!matches.length && <p>{lessons.length ? "没有匹配的课次。" : "课程还没有课次。"}</p>}
    <p className="export-hint">搜索不会清除已选课次，每次最多选择500节。</p>
  </fieldset>;
}
