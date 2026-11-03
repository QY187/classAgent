"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import SidebarIcon from "../SidebarIcon";
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
  const usedPercent = quota && quota.daily_limit > 0 ? Math.min(100, quota.used_tokens / quota.daily_limit * 100) : 0;
  const reservedPercent = quota && quota.daily_limit > 0 ? Math.min(100 - usedPercent, quota.reserved_tokens / quota.daily_limit * 100) : 0;
  return <>
    <section className="token-quota-card token-quota-overview" aria-labelledby="token-quota-title">
      <div className="token-quota-card-heading">
        <div className="token-quota-title-group"><span className="token-quota-section-icon"><SidebarIcon name="quota" /></span><div><h2 id="token-quota-title">我的每日 Token 额度</h2><p>每天北京时间 00:00 重置，未用完的额度不累计。</p></div></div>
        <button className="button button-secondary token-quota-refresh" type="button" disabled={loading} onClick={() => void load()}><QuotaIcon name="refresh" />{loading ? "读取中…" : "刷新额度"}</button>
      </div>
      {error && <p className="token-quota-message is-error" role="alert">{error}</p>}
      {quota ? <>
        <div className="token-quota-balance-row">
          <div className="token-quota-balance"><div className="token-quota-balance-label">当前可用 <span className={`token-quota-badge ${!quota.enabled ? "is-neutral" : quota.remaining_tokens > 0 ? "is-success" : "is-warning"}`}>{!quota.enabled ? "未启用限制" : quota.remaining_tokens > 0 ? "正常可用" : "暂无可用额度"}</span></div><div className="token-quota-balance-value"><strong>{tokenCount(quota.remaining_tokens)}</strong><span>Token</span></div></div>
          <dl className="token-quota-numbers"><div><dt><span className="token-quota-dot is-total" />每日上限</dt><dd>{tokenCount(quota.daily_limit)}</dd></div><div><dt><span className="token-quota-dot is-used" />今日已用</dt><dd>{tokenCount(quota.used_tokens)}</dd></div><div><dt><span className="token-quota-dot is-reserved" />预留额度</dt><dd>{tokenCount(quota.reserved_tokens)}</dd></div></dl>
        </div>
        <div className="token-quota-distribution"><div className="token-quota-distribution-label"><span>今日额度分布</span><span>已用及预留 {Math.round(usedPercent + reservedPercent)}%</span></div><div className="token-quota-progress" role="img" aria-label={`已用 ${tokenCount(quota.used_tokens)}，预留 ${tokenCount(quota.reserved_tokens)}，可用 ${tokenCount(quota.remaining_tokens)} Token`}><span className="is-used" style={{ width: `${usedPercent}%` }} /><span className="is-reserved" style={{ width: `${reservedPercent}%` }} /></div><div className="token-quota-legend"><span><i className="token-quota-dot is-used" />已使用</span><span><i className="token-quota-dot is-reserved" />预留中</span><span><i className="token-quota-dot is-available" />可用额度</span></div></div>
        {quota.remaining_tokens === 0 && <p className="token-quota-message is-warning" role="status">今日额度已用完或已被预留，请等待任务结算、次日重置，或联系管理员调整。</p>}
        <details className="token-quota-help"><summary><QuotaIcon name="info" /><span>额度如何计算？</span><span className="token-quota-help-hint">计量范围与预留说明</span><QuotaIcon name="chevron" /></summary><div><p>统计范围：{quota.scope_label}。一次提问可能包含多次模型调用，均计入用量；读取已有结果不重复扣减。</p><p>语音转写、向量化和重排暂不计入此 Token 额度。</p><p>调用前保守预留输入与输出预算，再按供应商实际用量结算。预留不代表已消耗；用量未确认时保留预留，等待管理员核对。</p>{!quota.enabled && <p>当前环境已关闭额度拦截。</p>}</div></details>
      </> : !error && <div className="token-quota-empty" role="status">正在读取额度…</div>}
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
  function closeLedger() {
    const userId = selected?.user_id;
    setSelected(null);
    if (userId) requestAnimationFrame(() => document.getElementById(`token-quota-details-${userId}`)?.focus({ preventScroll: true }));
  }
  return <section className="token-quota-card token-quota-admin" aria-labelledby="quota-admin-title">
    <div className="token-quota-card-heading"><div><h2 id="quota-admin-title">用户额度管理</h2><p>设置每日使用上限，或查看每位用户的模型调用明细。</p></div><span className="token-quota-badge is-neutral">管理员</span></div>
    <form className="token-quota-search" onSubmit={search}><label className="token-quota-search-field"><span className="sr-only">按用户名查找</span><SidebarIcon name="search" /><input className="field" type="search" placeholder="搜索用户名…" maxLength={100} value={query} onChange={event => setQuery(event.target.value)} /></label><button className="button button-primary" type="submit">查找用户</button><button className="button button-secondary token-quota-refresh" type="button" onClick={() => setRevision(value => value + 1)}><QuotaIcon name="refresh" />刷新列表</button></form>
    {error && <p className="token-quota-message is-error" role="alert">{error}</p>}{notice && <p className="token-quota-message is-success" role="status">{notice}</p>}
    {data ? <><div className="token-quota-table token-quota-users"><table><thead><tr><th scope="col">用户</th><th scope="col">今日用量</th><th scope="col">当前可用</th><th scope="col">每日额度</th><th scope="col">操作</th></tr></thead><tbody>{data.items.map(user => <tr key={user.user_id}>
      <td className="token-quota-user-cell"><div className="token-quota-user"><span className="token-quota-avatar" aria-hidden="true">{user.username.charAt(0).toUpperCase()}</span><div><strong>{user.username}</strong><span>{user.custom_daily_limit === null ? "使用默认额度" : user.custom_daily_limit === 0 ? "已暂停调用" : "自定义额度"}</span></div></div></td>
      <td data-label="今日用量"><strong className="token-quota-table-number">{tokenCount(user.used_tokens)}</strong><small>预留 {tokenCount(user.reserved_tokens)}</small></td>
      <td data-label="当前可用"><strong className="token-quota-table-number token-quota-remaining">{tokenCount(user.remaining_tokens)}</strong><small>Token</small></td>
      <td className="token-quota-limit-cell" data-label="每日额度"><input className="field" type="number" min={0} max={1000000000} step={1} aria-label={`${user.username}的每日Token额度`} value={drafts[user.user_id] ?? ""} placeholder={`默认 ${tokenCount(user.default_daily_limit)}`} onChange={event => setDrafts(current => ({ ...current, [user.user_id]: event.target.value }))} /></td>
      <td className="token-quota-action-cell"><div className="token-quota-actions"><button className="button button-secondary" type="button" disabled={!!saving} onClick={() => void save(user)}>{saving === user.user_id ? "保存中…" : "保存额度"}</button><button id={`token-quota-details-${user.user_id}`} className="token-quota-detail-button" type="button" onClick={() => setSelected(user)}>查看用量<QuotaIcon name="arrow" /></button></div></td>
    </tr>)}</tbody></table>{!data.items.length && <div className="token-quota-empty"><SidebarIcon name="search" /><strong>没有找到匹配的用户</strong><span>试试其他用户名，或清空搜索查看全部用户。</span></div>}</div><div className="token-quota-pagination"><span>共 {data.total} 位用户</span><div><button className="button button-secondary" type="button" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>第 {page} 页</span><button className="button button-secondary" type="button" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}>下一页</button></div></div></> : !error && <div className="token-quota-empty" role="status">正在读取用户额度…</div>}
    <p className="token-quota-admin-note"><QuotaIcon name="info" />额度留空使用默认值，填写 0 暂停新调用。调整立即生效，不清空今日已用量，也不中止已发出的调用。</p>
    {selected && <QuotaLedger user={selected} onClose={closeLedger} onChanged={() => { setRevision(value => value + 1); onChanged(); }} />}
  </section>;
}

function QuotaLedger({ user, onClose, onChanged }: { user: QuotaUser; onClose: () => void; onChanged: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [day, setDay] = useState(user.day);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<TokenEntries | null>(null);
  const [revision, setRevision] = useState(0);
  const [actuals, setActuals] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState("");
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const previousOverflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => { element.close(); document.body.style.overflow = previousOverflow; };
  }, []);
  useEffect(() => { setDay(user.day); setPage(1); setActuals({}); setNotice(""); }, [user.user_id, user.day]);
  useEffect(() => {
    if (!day) { setData(null); setError(""); return; }
    const controller = new AbortController(); setError(""); setData(null);
    request<TokenEntries>(`/quotas/admin/users/${user.user_id}/entries?${new URLSearchParams({ day, page: String(page) })}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result); }).catch(err => { if (!controller.signal.aborted) setError(errorMessage(err)); });
    return () => controller.abort();
  }, [user.user_id, day, page, revision]);
  async function resolve(id: string) {
    if (saving) return;
    const raw = actuals[id] ?? ""; const actual = Number(raw);
    if (!raw.trim() || !Number.isSafeInteger(actual) || actual < 0 || actual > 1000000000) { setError("请先核对供应商记录，再输入实际 Token 数；确认没有消耗时才填写 0。"); return; }
    setSaving(id); setError(""); setNotice("");
    try {
      await request(`/quotas/admin/entries/${id}/resolve`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actual_tokens: actual }) });
      setNotice("该调用已按核对用量结算。"); setRevision(value => value + 1); onChanged();
    } catch (err) { setError(errorMessage(err)); } finally { setSaving(""); }
  }
  return <dialog ref={dialog} className="token-quota-dialog" aria-labelledby={titleId} aria-modal="true"
    onCancel={event => { if (saving) event.preventDefault(); }}
    onClose={event => { if (!event.currentTarget.open) onClose(); }}
    onKeyDown={event => {
      if (event.key !== "Tab") return;
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), summary, [tabindex="0"]')).filter(element => element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}
    onClick={event => {
      if (saving || event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
    <header className="token-quota-dialog-header"><div className="token-quota-title-group"><span className="token-quota-section-icon"><SidebarIcon name="notebook" /></span><div><span className="token-quota-eyebrow">用量明细</span><h2 id={titleId}>{user.username} 的模型用量</h2></div></div><button className="token-quota-close" type="button" autoFocus aria-label="关闭用量详情" disabled={!!saving} onClick={() => dialog.current?.close()}><QuotaIcon name="close" /></button></header>
    <div className="token-quota-dialog-toolbar"><label className="field-label">用量日期（北京时间）<input className="field" type="date" value={day} disabled={!!saving} onChange={event => { setDay(event.target.value); setPage(1); setActuals({}); setNotice(""); }} /></label><button className="button button-secondary token-quota-refresh" type="button" disabled={!day || !!saving} onClick={() => setRevision(value => value + 1)}><QuotaIcon name="refresh" />刷新明细</button><span>跨日调用计入发起当天</span></div>
    <div className="token-quota-dialog-body">
      {error && <p className="token-quota-message is-error" role="alert">{error}</p>}{notice && <p className="token-quota-message is-success" role="status">{notice}</p>}
      {data ? <><div className="token-quota-table token-quota-ledger-table"><table><thead><tr><th scope="col">调用时间</th><th scope="col">模型 / 用途</th><th scope="col">状态</th><th scope="col">Token 用量</th><th scope="col">核对结算</th></tr></thead><tbody>{data.items.map(entry => <tr key={entry.id}>
        <td data-label="调用时间" className="token-quota-time">{callTime(entry.created_at)}</td><td data-label="模型 / 用途"><strong className="token-quota-model">{entry.model}</strong><small>{purposeLabel(entry.purpose)}</small></td>
        <td data-label="状态"><span className="token-quota-badge" data-status={entry.status}>{tokenStatus(entry.status)}</span></td>
        <td data-label="Token 用量"><strong className="token-quota-table-number">{entry.actual_tokens === null ? "待确认" : tokenCount(entry.actual_tokens)}</strong><small>预留 {tokenCount(entry.reserved_tokens)}</small>{entry.input_tokens !== null && entry.output_tokens !== null && <small>输入 {tokenCount(entry.input_tokens)} · 输出 {tokenCount(entry.output_tokens)}</small>}</td>
        <td className="token-quota-reconcile-cell" data-label="核对结算">{canResolve(entry) ? <div className="token-quota-actions"><input className="field" type="number" min={0} max={1000000000} step={1} placeholder="实际 Token" disabled={!!saving} aria-label={`记录${entry.id}的实际Token`} value={actuals[entry.id] ?? ""} onChange={event => setActuals(current => ({ ...current, [entry.id]: event.target.value }))} /><button className="button button-secondary" type="button" disabled={!!saving} onClick={() => void resolve(entry.id)}>{saving === entry.id ? "结算中…" : "按核对用量结算"}</button></div> : <span className="token-quota-settled-note">{entry.status === "reserved" ? "等待调用完成" : entry.status === "released" ? "预留已释放" : entry.status === "settled" ? "已完成结算" : "—"}</span>}</td>
      </tr>)}</tbody></table>{!data.items.length && <div className="token-quota-empty"><SidebarIcon name="notebook" /><strong>当天没有模型调用记录</strong><span>可以选择其他日期查看历史用量。</span></div>}</div></> : !error && <div className="token-quota-empty" role="status">{day ? "正在读取用量…" : "请选择要查看的日期。"}</div>}
      <details className="token-quota-help token-quota-ledger-help"><summary><QuotaIcon name="info" /><span>如何核对待确认用量？</span><QuotaIcon name="chevron" /></summary><div>仅核对待确认或已预留超过 15 分钟的记录。请先确认调用已停止，并查阅供应商记录，再填写实际 Token 数。填写 0 表示确认没有消耗，不能将未知用量填为 0。</div></details>
    </div>
    <footer className="token-quota-pagination token-quota-dialog-footer"><span>{data ? `共 ${data.total} 次调用` : "模型调用记录"}</span><div><button className="button button-secondary" type="button" disabled={page <= 1 || !!saving || !data} onClick={() => setPage(value => value - 1)}>上一页</button><span>第 {page} 页</span><button className="button button-secondary" type="button" disabled={!data || page * data.page_size >= data.total || !!saving} onClick={() => setPage(value => value + 1)}>下一页</button></div></footer>
  </dialog>;
}

function callTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function purposeLabel(value: string) {
  return ({ chat: "对话与任务处理", summary: "课堂纪要", quiz: "小测生成", rag_answer: "课程问答", rag_answer_stream: "课程流式问答" } as Record<string, string>)[value] ?? value;
}

function QuotaIcon({ name }: { name: "refresh" | "info" | "arrow" | "close" | "chevron" }) {
  const paths = { refresh: "M20 7v5h-5M4 17v-5h5M6.1 6.1a8 8 0 0 1 13.2 3.1M4.7 14.8a8 8 0 0 0 13.2 3.1", info: "M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0", arrow: "M5 12h14m-5-5 5 5-5 5", close: "m6 6 12 12M6 18 18 6", chevron: "m7 10 5 5 5-5" };
  return <svg className="token-quota-inline-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
