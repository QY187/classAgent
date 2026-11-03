export type TokenQuota = {
  user_id: string; day: string; timezone: string; resets_at: string; enabled: boolean;
  daily_limit: number; custom_daily_limit: number | null; default_daily_limit: number;
  used_tokens: number; reserved_tokens: number; remaining_tokens: number; scope_label: string;
};
export type QuotaUser = TokenQuota & { username: string };
export type QuotaUsers = { items: QuotaUser[]; total: number; page: number; page_size: number };
export type TokenEntry = {
  id: string; day: string; model: string; purpose: string; status: string;
  reserved_tokens: number; actual_tokens: number | null; input_tokens: number | null; output_tokens: number | null;
  created_at: string; finished_at: string | null; resolved_by: string | null;
};
export type TokenEntries = { items: TokenEntry[]; total: number; page: number; page_size: number };
export const tokenCount = (value: number) => value.toLocaleString("zh-CN");
export const tokenStatus = (value: string) => ({ reserved: "预留中", uncertain: "待核对", settled: "已结算", released: "已释放" }[value] ?? value);
export function canResolve(entry: TokenEntry, now = Date.now()) {
  return entry.status === "uncertain" || (entry.status === "reserved" && now - Date.parse(entry.created_at) >= 15 * 60000);
}
