"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, request } from "../../lib/api";
import { canResolve, tokenCount, tokenStatus, type TokenQuota, type QuotaUser, type QuotaUsers, type TokenEntries } from "../../lib/token-quotas";
import "./token-quota.css";

export default function TokenQuotaSettings({ isAdmin }: { isAdmin: boolean }) {
  const [quota, setQuota] = useState<TokenQuota | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError("");
    try { const result = await request<TokenQuota>("/quotas/me", { signal }); if (!signal?.aborted) setQuota(result); }
    catch (err) { if (!signal?.aborted) setError(errorMessage(err)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  return <>
    <section className="settings-card token-quota-card" aria-labelledby="token-quota-title">
      <div className="settings-section-heading token-quota-heading"><div><span className="settings-kicker">AI 使用额度</span><h2 id="token-quota-title">我的每日 Token 额度</h2><p>每天北京时间 00:00 重置，未用完的额度不累计。</p></div><button className="button button-secondary" type="button" disabled={loading} onClick={() => void load()}>{loading ? "读取中…" : "刷新额度"}</button></div>
      {error && <p className="token-quota-error" role="alert">{error}</p>}
      {quota ? <><dl className="token-quota-numbers">
        <div><dt>每日上限</dt><dd>{tokenCount(quota.daily_limit)}</dd></div><div><dt>今日已用</dt><dd>{tokenCount(quota.used_tokens)}</dd></div>
        <div><dt>预留额度</dt><dd>{tokenCount(quota.reserved_tokens)}</dd></div><div><dt>当前可用</dt><dd>{tokenCount(quota.remaining_tokens)}</dd></div>
      </dl><div className="token-quota-notes"><p>统计范围：{quota.scope_label}。一次提问可能包含多次模型调用，均计入用量；读取已有结果不重复扣减。</p><p>语音转写、向量化和重排暂不计入此 Token 额度。</p><p>系统在调用前保守预留输入与输出预算，再按供应商实际用量结算。预留不代表已消耗；用量未确认时保留预留，等待管理员核对。</p>{!quota.enabled && <p role="status">当前环境已关闭额度拦截。</p>}{quota.remaining_tokens === 0 && <p className="token-quota-error" role="status">今日可用额度已用完或已被预留，请等待任务结算、次日重置，或联系管理员调整。</p>}</div></> : !error && <p className="token-quota-notes" role="status">正在读取额度…</p>}
    </section>
    {isAdmin && <QuotaAdministration onChanged={() => void load()} />}
  </>;
}

function QuotaAdministration({ onChanged }: { onChanged: () => void }) {
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<QuotaUsers | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<QuotaUser | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setError(""); setData(null);
    request<QuotaUsers>(`/quotas/admin/users?${new URLSearchParams({ query: applied, page: String(page) })}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setData(result); setDrafts(Object.fromEntries(result.items.map(item => [item.user_id, item.custom_daily_limit === null ? "" : String(item.custom_daily_limit)]))); } })
      .catch(err => { if (!controller.signal.aborted) setError(errorMessage(err)); });
    return () => controller.abort();
  }, [applied, page, revision]);
  async function save(user: QuotaUser) {
    const raw = drafts[user.user_id] ?? "";
    const limit = raw.trim() === "" ? null : Number(raw);
    if (limit !== null && (!Number.isSafeInteger(limit) || limit < 0 || limit > 1000000000)) { setError("每日额度请输入 0 到 1,000,000,000 之间的整数，留空使用默认额度。"); return; }
    setSaving(user.user_id); setError(""); setNotice("");
    try {
      await request(`/quotas/admin/users/${user.user_id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ daily_limit: limit }) });
      setNotice(`${user.username} 的每日额度已更新，今日已用量保持不变。`); setRevision(value => value + 1); onChanged();
    } catch (err) { setError(errorMessage(err)); } finally { setSaving(""); }
  }
  function search(event: FormEvent) { event.preventDefault(); setPage(1); setApplied(query.trim()); setRevision(value => value + 1); }
  return <section className="settings-card token-quota-card" aria-labelledby="quota-admin-title">
    <div className="settings-section-heading"><span className="settings-kicker">管理员</span><h2 id="quota-admin-title">用户额度管理</h2><p>修改后立即影响新的模型调用；不会清空已用量或中止已经发出的调用。填写 0 可暂停该用户的新模型调用，留空恢复默认额度。</p></div>
    <form className="token-quota-search" onSubmit={search}><label className="field-label">按用户名查找<input className="field" maxLength={100} value={query} onChange={event => setQuery(event.target.value)} /></label><button className="button button-secondary" type="submit">查找用户</button><button className="button button-secondary" type="button" onClick={() => setRevision(value => value + 1)}>刷新列表</button></form>
    {error && <p className="token-quota-error" role="alert">{error}</p>}{notice && <p className="token-quota-notes" role="status">{notice}</p>}
    {data ? <><div className="token-quota-table"><table><thead><tr><th>用户</th><th>今日已用 / 预留</th><th>当前可用</th><th>每日额度</th><th>操作</th></tr></thead><tbody>{data.items.map(user => <tr key={user.user_id}><td>{user.username}</td><td>{tokenCount(user.used_tokens)} / {tokenCount(user.reserved_tokens)}</td><td>{tokenCount(user.remaining_tokens)}</td><td><input className="field" type="number" min={0} max={1000000000} step={1} aria-label={`${user.username}的每日Token额度`} value={drafts[user.user_id] ?? ""} placeholder={`默认 ${tokenCount(user.default_daily_limit)}`} onChange={event => setDrafts(current => ({ ...current, [user.user_id]: event.target.value }))} /></td><td><div className="token-quota-actions"><button className="button button-primary" type="button" disabled={!!saving} onClick={() => void save(user)}>{saving === user.user_id ? "保存中…" : "保存额度"}</button><button className="button button-secondary" type="button" onClick={() => setSelected(user)}>查看用量</button></div></td></tr>)}</tbody></table>{!data.items.length && <p className="token-quota-notes">没有匹配的用户。</p>}</div><div className="token-quota-pagination"><span>共 {data.total} 位用户 · 第 {page} 页</span><button className="button button-secondary" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><button className="button button-secondary" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}>下一页</button></div></> : !error && <p className="token-quota-notes" role="status">正在读取用户额度…</p>}
    {selected && <QuotaLedger user={selected} onClose={() => setSelected(null)} onChanged={() => { setRevision(value => value + 1); onChanged(); }} />}
  </section>;
}

function QuotaLedger({ user, onClose, onChanged }: { user: QuotaUser; onClose: () => void; onChanged: () => void }) {
  const [day, setDay] = useState(user.day);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TokenEntries | null>(null);
  const [revision, setRevision] = useState(0);
  const [actuals, setActuals] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState("");
  useEffect(() => { setDay(user.day); setPage(1); setActuals({}); setNotice(""); }, [user.user_id, user.day]);
  useEffect(() => {
    if (!day) return;
    const controller = new AbortController(); setError(""); setData(null);
    request<TokenEntries>(`/quotas/admin/users/${user.user_id}/entries?${new URLSearchParams({ day, page: String(page) })}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result); }).catch(err => { if (!controller.signal.aborted) setError(errorMessage(err)); });
    return () => controller.abort();
  }, [user.user_id, day, page, revision]);
  async function resolve(id: string) {
    const raw = actuals[id] ?? ""; const actual = Number(raw);
    if (!raw.trim() || !Number.isSafeInteger(actual) || actual < 0 || actual > 1000000000) { setError("请先核对供应商记录，再输入实际 Token 数；确认没有消耗时才填写 0。"); return; }
    setSaving(id); setError(""); setNotice("");
    try {
      await request(`/quotas/admin/entries/${id}/resolve`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actual_tokens: actual }) });
      setNotice("该调用已按核对用量结算。"); setRevision(value => value + 1); onChanged();
    } catch (err) { setError(errorMessage(err)); } finally { setSaving(""); }
  }
  return <div className="token-quota-ledger"><div className="token-quota-heading"><h3>{user.username} 的模型用量</h3><button className="button button-secondary" type="button" onClick={onClose}>关闭用量详情</button></div><label className="field-label">用量日期（北京时间）<input className="field" type="date" value={day} onChange={event => { setDay(event.target.value); setPage(1); }} /></label><p>仅核对待确认或已预留超过 15 分钟的记录。输入实际用量后结算；填写 0 表示确认没有消耗。跨日调用归入发起当天。</p>
    {error && <p className="token-quota-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {data ? <><div className="token-quota-table"><table><thead><tr><th>模型 / 用途</th><th>状态</th><th>预留 / 实际 Token</th><th>核对结算</th></tr></thead><tbody>{data.items.map(entry => <tr key={entry.id}><td>{entry.model}<br /><small>{entry.purpose}</small></td><td>{tokenStatus(entry.status)}</td><td>{tokenCount(entry.reserved_tokens)} / {entry.actual_tokens === null ? "未确认" : tokenCount(entry.actual_tokens)}</td><td>{canResolve(entry) ? <div className="token-quota-actions"><input className="field" type="number" min={0} max={1000000000} step={1} aria-label={`记录${entry.id}的实际Token`} value={actuals[entry.id] ?? ""} onChange={event => setActuals(current => ({ ...current, [entry.id]: event.target.value }))} /><button className="button button-secondary" type="button" disabled={!!saving} onClick={() => void resolve(entry.id)}>{saving === entry.id ? "结算中…" : "按核对用量结算"}</button></div> : "—"}</td></tr>)}</tbody></table>{!data.items.length && <p>当天没有模型调用记录。</p>}</div><div className="token-quota-pagination"><span>共 {data.total} 条 · 第 {page} 页</span><button className="button button-secondary" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><button className="button button-secondary" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}>下一页</button></div></> : !error && <p role="status">正在读取用量…</p>}
  </div>;
}
