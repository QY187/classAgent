"use client";

import { useState } from "react";

type Lesson = { id: string; title: string };
type Props = { lessons: Lesson[]; selectedIds: string[]; onChange: (ids: string[]) => void; disabled: boolean };

export default function QuizLessonPicker({ lessons, selectedIds, onChange, disabled }: Props) {
  const [query, setQuery] = useState("");
  const matching = lessons.filter((lesson) => lesson.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <fieldset className="quiz-lesson-picker" disabled={disabled}>
    <legend>选择课次 · 已选 {selectedIds.length} 节</legend>
    <div className="quiz-lesson-picker-toolbar">
      <input type="search" className="field" aria-label="搜索出题课次" placeholder="搜索课次名称" value={query} onChange={(event) => setQuery(event.target.value)} />
      <button type="button" className="button button-secondary" disabled={!matching.length || selectedIds.length >= 50} onClick={() => onChange([...new Set([...selectedIds, ...matching.map((lesson) => lesson.id)])].slice(0, 50))}>{query.trim() ? "选中搜索结果" : lessons.length > 50 ? "选择前 50 节" : "选中所有课次"}</button>
      <button type="button" className="button button-quiet" disabled={!selectedIds.length} onClick={() => onChange([])}>清空</button>
    </div>
    <div className="quiz-lesson-picker-list">{matching.map((lesson) => <label key={lesson.id} className={selectedIds.includes(lesson.id) ? "is-selected" : ""}>
      <input type="checkbox" checked={selectedIds.includes(lesson.id)} disabled={selectedIds.length >= 50 && !selectedIds.includes(lesson.id)} onChange={() => onChange(selectedIds.includes(lesson.id) ? selectedIds.filter((id) => id !== lesson.id) : [...selectedIds, lesson.id])} />
      <span>{lesson.title}</span>
    </label>)}</div>
    {!matching.length && <p>{lessons.length ? "没有匹配的课次" : "还没有课次，请先创建课次并完成转写。"}</p>}
    <p>最多选择 50 节课；所选课次都需要已有文字记录。</p>
  </fieldset>;
}
