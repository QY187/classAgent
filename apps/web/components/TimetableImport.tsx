"use client";

import { useState, type FormEvent } from "react";
import { errorMessage, request } from "../lib/api";
import { assessImport, type ImportEntry, type ImportPreview, type ImportRow } from "../lib/timetable-import";
import { patternLabels, weekdays, type Entry, type Semester } from "../lib/timetable";
import "./timetable-import.css";

export default function TimetableImport({ semester, existing, onClose, onImported }: {
  semester: Semester; existing: Entry[]; onClose: () => void;
  onImported: (result: { added: number; skipped: number }) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const assessments = assessImport(rows, existing, semester);
  const selected = rows.filter((row) => row.selected);
  const selectedErrors = assessments.some((value, index) => rows[index].selected && value.errors.length > 0);
  const count = rows.filter((row, index) => row.selected && !assessments[index].duplicate && assessments[index].errors.length === 0).length;

  function edit(index: number, key: keyof ImportEntry, value: string | number) {
    setRows((current) => current.map((row, i) => i === index ? { ...row, entry: { ...row.entry, [key]: value } } : row));
  }
  async function parse(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    if (!/\.(pdf|csv|xls)$/i.test(file.name)) { setError("请选择 PDF、XLS 或 CSV 课表文件"); return; }
    if (file.size > 8 * 1024 * 1024) { setError("文件不能超过 8 MB"); return; }
    setBusy(true); setError(""); setPreview(null); setRows([]);
    try {
      const body = new FormData(); body.append("file", file);
      const result = await request<ImportPreview>(`/timetable/semesters/${semester.id}/import/preview`, { method: "POST", body, signal: AbortSignal.timeout(180000) });
      setPreview(result);
      setRows(result.candidates.map((row) => ({ ...row, selected: row.status === "ready" })));
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (busy || selectedErrors || selected.length === 0) return;
    setBusy(true); setError("");
    try {
      const result = await request<{ added: number; skipped: number }>(`/timetable/semesters/${semester.id}/import`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: selected.map((row) => row.entry) }), signal: AbortSignal.timeout(60000),
      });
      onImported(result);
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <div className="modal-backdrop"><section className="modal timetable-import-modal" role="dialog" aria-modal="true" aria-label="导入解析课程表" onKeyDown={(event) => { if (event.key === "Escape" && !busy) onClose(); }}>
    <div className="import-heading"><div><h2>导入解析课程表</h2><p>导入到「{semester.name}」 · {semester.start_date} 开学 · {semester.week_count} 周</p></div><button className="button button-secondary" disabled={busy} onClick={onClose}>关闭</button></div>
    <p className="timetable-help">支持 XLS Excel、文字版和扫描版 PDF、CSV 清单，最大 8 MB。PDF 最多 15 页，其中扫描页最多 5 页，会自动使用本地 OCR。解析结果可在下方查看和校对，确认后才会保存。</p>
    <form onSubmit={parse} className="import-upload">
      <label className="field-label">选择课表文件<input type="file" accept=".pdf,.csv,.xls,application/pdf,text/csv,application/vnd.ms-excel" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setRows([]); setError(""); }} /></label>
      <button className="button button-primary" disabled={!file || busy} type="submit">{busy && !preview ? "正在解析…" : "解析文件"}</button>
    </form>
    {error && <p className="notice" role="alert">{error}</p>}
    {preview && <>
      <div className="import-summary"><strong>识别到 {rows.length} 条安排</strong><span>勾选 {selected.length} 条 · 可新增 {count} 条</span><button className="button button-quiet" disabled={busy} onClick={() => setRows((current) => current.map((row) => ({ ...row, selected: false })))}>取消全选</button></div>
      <p className="timetable-help">{preview.message} 周次不连续时会拆成多条；重复记录会跳过。待完善或冲突的记录默认不勾选，可修改后选择。</p>
      {preview.warnings.map((warning, index) => <p className="notice" key={index}>{warning}</p>)}
      <div className="import-table-scroll"><table className="import-table"><thead><tr><th>选择</th><th>课程名称</th><th>星期</th><th>小节</th><th>周次</th><th>频率</th><th>教室</th><th>教师</th></tr></thead>
        <tbody>{rows.map((row, index) => <ImportRowEditor key={index} index={index} row={row} semester={semester} busy={busy} errors={assessments[index].errors} duplicate={assessments[index].duplicate} onSelect={(selected) => setRows((current) => current.map((item, i) => i === index ? { ...item, selected } : item))} onEdit={(key, value) => edit(index, key, value)} />)}</tbody>
      </table></div>
      {selectedErrors && <p className="notice" role="alert">已勾选的安排存在缺项或冲突，请修改或取消勾选后再导入。</p>}
      <div className="modal-actions"><span className="timetable-help">只新增排课，已有课程安排会保留。</span><button className="button button-primary" disabled={busy || selectedErrors || selected.length === 0} onClick={confirm}>{busy ? "正在导入…" : `确认导入 ${selected.length} 条`}</button></div>
    </>}
  </section></div>;
}

function ImportRowEditor({ row, index, semester, busy, errors, duplicate, onSelect, onEdit }: {
  row: ImportRow; index: number; semester: Semester; busy: boolean; errors: string[]; duplicate: boolean;
  onSelect: (value: boolean) => void; onEdit: (key: keyof ImportEntry, value: string | number) => void;
}) {
  const label = (field: string) => `第${index + 1}条${field}`;
  return <><tr className={errors.length ? "import-row-warning" : ""}>
    <td><input type="checkbox" aria-label={label("选择")} checked={row.selected} onChange={(event) => onSelect(event.target.checked)} disabled={busy} /></td>
    <td><input className="field" aria-label={label("课程名称")} value={row.entry.title} maxLength={100} disabled={busy} onChange={(event) => onEdit("title", event.target.value)} /></td>
    <td><select className="field" aria-label={label("星期")} value={row.entry.weekday} disabled={busy} onChange={(event) => onEdit("weekday", Number(event.target.value))}><option value={0}>待选择</option>{[1, 2, 3, 4, 5, 6, 7].map((day) => <option key={day} value={day}>{weekdays[day % 7]}</option>)}</select></td>
    <td><div className="import-range">{(["start_period", "end_period"] as const).map((key, i) => <input key={key} className="field" type="number" min={1} max={semester.periods.length} aria-label={label(i ? "结束小节" : "开始小节")} value={row.entry[key] || ""} disabled={busy} onChange={(event) => onEdit(key, Number(event.target.value))} />)}</div></td>
    <td><div className="import-range">{(["start_week", "end_week"] as const).map((key, i) => <input key={key} className="field" type="number" min={1} max={semester.week_count} aria-label={label(i ? "结束周次" : "开始周次")} value={row.entry[key] || ""} disabled={busy} onChange={(event) => onEdit(key, Number(event.target.value))} />)}</div></td>
    <td><select className="field" aria-label={label("上课频率")} value={row.entry.week_pattern} disabled={busy} onChange={(event) => onEdit("week_pattern", event.target.value)}>{Object.entries(patternLabels).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></td>
    <td><input className="field" aria-label={label("教室")} value={row.entry.room} maxLength={100} disabled={busy} onChange={(event) => onEdit("room", event.target.value)} /></td>
    <td><input className="field" aria-label={label("教师")} value={row.entry.teacher} maxLength={100} disabled={busy} onChange={(event) => onEdit("teacher", event.target.value)} /></td>
  </tr><tr className="import-source-row"><td /><td colSpan={7}>
    <span className={errors.length ? "import-status is-warning" : "import-status"}>{errors.length ? errors.join("；") : duplicate ? "重复安排，将自动跳过" : "可导入"}</span>
    {row.warnings.map((warning, i) => <span className="import-note" key={i}>{warning}</span>)}
    <details><summary>{row.source} · 查看识别原文</summary><pre>{row.raw}</pre></details>
  </td></tr></>;
}
