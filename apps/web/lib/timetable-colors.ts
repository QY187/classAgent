const legacy: Record<string, string> = { teal: "#14B8A6", purple: "#8B5CF6", blue: "#3B82F6", amber: "#F59E0B", rose: "#EC4899" };

export function timetableColorStyle(color: string) {
  const value = legacy[color] ?? color;
  const accent = /^#[0-9a-f]{6}$/i.test(value) ? value : legacy.teal;
  const channels = [1, 3, 5].map((index) => parseInt(accent.slice(index, index + 2), 16));
  const blend = (target: number, amount: number) => `rgb(${channels.map((channel) => Math.round(channel * (1 - amount) + target * amount)).join(", ")})`;
  return { "--course-accent": accent, "--course-fill": blend(255, 0.68), "--course-ink": blend(20, 0.62) };
}
