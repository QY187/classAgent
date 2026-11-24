export type Period = { start: string; end: string };
export type Semester = {
  id: string;
  name: string;
  start_date: string;
  week_count: number;
  periods: Period[];
  is_active: boolean;
};
export type Entry = {
  id: string;
  course_id: string | null;
  title: string;
  room: string;
  teacher: string;
  weekday: number;
  start_period: number;
  end_period: number;
  start_week: number;
  end_week: number;
  week_pattern: "all" | "odd" | "even";
  color: string;
  is_all_day?: boolean;
};
export type WeekView = {
  semester: Semester | null;
  today: string;
  days: string[];
  entries: Entry[];
  week: number | null;
  current_week: number | null;
  status: "unset" | "before" | "current" | "after";
};
export const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
export const patternLabels = { all: "每周", odd: "单周", even: "双周" };

export function groupPeriods(periods: Period[]) {
  const groups: { start_period: number; end_period: number; start: string; end: string }[] = [];
  const minutes = (value: string) => {
    const [hour, minute] = value.split(":").map(Number);
    return hour * 60 + minute;
  };
  periods.forEach((period, index) => {
    const previous = groups.at(-1);
    if (previous && minutes(period.start) - minutes(previous.end) === 5) {
      previous.end_period = index + 1;
      previous.end = period.end;
    } else {
      groups.push({ start_period: index + 1, end_period: index + 1, ...period });
    }
  });
  return groups;
}

export function calendarDate(value: string) {
  // 日期由服务端按北京时间给出，以 UTC 读取日历字段可避免浏览器时区偏移。
  return new Date(value + "T00:00:00Z");
}

// 连通的重叠时段共用一组卡片；前后相邻但不重叠的课程仍独立展示。
export function overlappingEntries(entries: Entry[]) {
  const clusters: Entry[][] = [];
  for (const entry of [...entries].sort((a, b) => a.start_period - b.start_period || a.title.localeCompare(b.title, "zh-CN"))) {
    const last = clusters.at(-1);
    if (last && entry.start_period <= Math.max(...last.map((item) => item.end_period))) last.push(entry);
    else clusters.push([entry]);
  }
  return clusters;
}
