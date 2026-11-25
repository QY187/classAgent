import type { Entry, Semester } from "./timetable";

export type ImportEntry = Omit<Entry, "id">;
export type ImportRow = {
  source: string; raw: string; entry: ImportEntry; warnings: string[]; errors: string[];
  status: string; selected: boolean;
};
export type ImportPreview = { filename: string; candidates: Omit<ImportRow, "selected">[]; warnings: string[]; message: string };

function weeks(entry: ImportEntry) {
  return Array.from({ length: Math.max(0, Math.min(52, entry.end_week) - entry.start_week + 1) }, (_, index) => entry.start_week + index)
    .filter((week) => entry.week_pattern === "all" || week % 2 === (entry.week_pattern === "odd" ? 1 : 0));
}
function same(left: ImportEntry, right: ImportEntry) {
  const keys: (keyof ImportEntry)[] = ["title", "room", "teacher", "weekday", "start_period", "end_period", "start_week", "end_week", "week_pattern"];
  return keys.every((key) => left[key] === right[key]) && !!left.is_all_day === !!right.is_all_day;
}
function overlaps(left: ImportEntry, right: ImportEntry) {
  if (left.is_all_day && right.is_all_day) return false;
  if (left.weekday !== right.weekday || left.start_period > right.end_period || left.end_period < right.start_period) return false;
  const rightWeeks = new Set(weeks(right));
  return weeks(left).some((week) => rightWeeks.has(week));
}
export function assessImport(rows: ImportRow[], existing: Entry[], semester: Semester) {
  return rows.map((row, index) => {
    const entry = row.entry;
    const errors: string[] = [];
    if (!entry.title.trim()) errors.push("请填写课程名称");
    if (!Number.isInteger(entry.weekday) || entry.weekday < 1 || entry.weekday > 7) errors.push("请选择星期");
    if (![entry.start_period, entry.end_period].every(Number.isInteger) || entry.start_period < 1 || entry.end_period < entry.start_period || entry.end_period > semester.periods.length) errors.push("请核对小节范围");
    if (![entry.start_week, entry.end_week].every(Number.isInteger) || entry.start_week < 1 || entry.end_week < entry.start_week || entry.end_week > semester.week_count || weeks(entry).length === 0) errors.push("请核对周次与单双周");
    if (errors.length) return { errors, duplicate: false };
    const duplicate = existing.some((other) => same(entry, other)) || rows.some((other, otherIndex) => otherIndex < index && other.selected && same(entry, other.entry));
    if (!duplicate) {
      const conflict = existing.find((other) => overlaps(entry, other));
      if (conflict) errors.push(`与已有课程「${conflict.title}」冲突`);
      const inside = rows.find((other, otherIndex) => otherIndex !== index && other.selected && !same(entry, other.entry) && overlaps(entry, other.entry));
      if (inside) errors.push(`与本次导入的「${inside.entry.title}」冲突`);
    }
    return { errors, duplicate };
  });
}
