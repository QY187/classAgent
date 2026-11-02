"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { errorMessage, request } from "../../lib/api";
import type { AuthUser } from "../../lib/auth";
import { count, dateTime, duration, outcomeLabel, statusLabel, tokenCoverage, type Overview, type Trace, type TraceList } from "../../lib/monitoring";
import TraceDetails from "../../components/monitoring/TraceDetails";

type Filters = { hours: string; status: string; requestId: string; tool: string };
const initialFilters: Filters = { hours: "24", status: "", requestId: "", tool: "" };

export default function MonitoringPage() {
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [authError, setAuthError] = useState("");
  const [filters, setFilters] = useState(initialFilters);
  const [applied, setApplied] = useState(initialFilters);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [list, setList] = useState<TraceList | null>(null);
  const [tools, setTools] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState("");
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Trace | null>(null);
  const [detailError, setDetailError] = useState("");
  const detailRef = useRef<HTMLElement>(null);
  const windowEnd = useRef(new Date().toISOString());

  useEffect(() => {
    const controller = new AbortController();
    request<AuthUser>("/auth/me", { signal: controller.signal }).then(user => setAuthorized(user.role === "admin"))
      .catch(err => { if (!controller.signal.aborted) setAuthError(errorMessage(err)); });
    const restore = () => setSelected(new URLSearchParams(window.location.search).get("trace") ?? "");
    restore(); window.addEventListener("popstate", restore);
    return () => { controller.abort(); window.removeEventListener("popstate", restore); };
  }, []);

  useEffect(() => {
    if (!authorized) return;
    const controller = new AbortController();
    const until = windowEnd.current;
    const since = new Date(Date.parse(until) - Number(applied.hours) * 3600000).toISOString();
    const params = new URLSearchParams({ since, until });
    if (applied.status) params.set("status", applied.status);
    if (applied.tool) params.set("tool", applied.tool);
    if (applied.requestId.trim()) params.set("request_id", applied.requestId.trim());
    setLoading(true); setError(""); setList(null); setOverview(null);
    Promise.all([
      request<Overview>(`/monitoring/overview?${params}`, { signal: controller.signal }),
      request<TraceList>(`/monitoring/traces?${params}&page=${page}`, { signal: controller.signal }),
      request<string[]>(`/monitoring/tools?${new URLSearchParams({ since, until })}`, { signal: controller.signal }),
    ]).then(([summary, rows, names]) => {
      if (controller.signal.aborted) return;
      setOverview(summary); setList(rows); setTools(names); setUpdatedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    }).catch(err => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [authorized, applied, page, revision]);

  useEffect(() => {
    if (!authorized || !selected) { setDetail(null); return; }
    const controller = new AbortController();
    setDetail(null); setDetailError("");
    request<Trace>(`/monitoring/traces/${encodeURIComponent(selected)}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setDetail(value); })
      .catch(err => { if (!controller.signal.aborted) setDetailError(errorMessage(err)); });
    return () => controller.abort();
  }, [authorized, selected, revision]);

  function refresh(event?: FormEvent) {
    event?.preventDefault(); windowEnd.current = new Date().toISOString();
    setApplied({ ...filters }); setPage(1); setRevision(value => value + 1);
  }
  function choose(id: string) {
    setSelected(id); const url = new URL(window.location.href);
    if (id) url.searchParams.set("trace", id); else url.searchParams.delete("trace");
    window.history.pushState(null, "", url);
    if (id) setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  if (authError) return <main className="content"><p className="notice" role="alert">{authError}</p></main>;
  if (authorized === null) return <main className="content"><p role="status">正在校验监控权限…</p></main>;
  if (!authorized) return <main className="content"><section className="panel"><div className="panel-body"><h1>运行监控</h1><p>此页面仅供管理员查看。你可以在自己的聊天消息中展开请求执行详情。</p></div></section></main>;

  const metrics = overview?.metrics ?? {};
  return <main className="content monitoring-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon" aria-hidden="true">↗</span><div className="page-hero-copy"><div className="eyebrow">管理员工作台</div><h1>运行监控</h1><p>从意图规划到工具与检索，查看每次请求的执行情况。</p></div><div className="page-hero-actions"><button className="button button-secondary" disabled={loading} onClick={() => refresh()}>刷新数据</button></div></section>
    <form className="monitor-filters panel" onSubmit={refresh}>
      <label>时间范围<select aria-label="时间范围" className="field" value={filters.hours} onChange={e => setFilters({ ...filters, hours: e.target.value })}><option value="1">最近 1 小时</option><option value="24">最近 24 小时</option><option value="168">最近 7 天</option><option value="720">最近 30 天</option></select></label>
      <label>执行状态<select aria-label="执行状态" className="field" value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">全部状态</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>执行工具<select aria-label="执行工具" className="field" value={filters.tool} onChange={e => setFilters({ ...filters, tool: e.target.value })}><option value="">全部工具</option>{[...new Set([...tools, ...(filters.tool ? [filters.tool] : [])])].map(name => <option key={name} value={name}>{name}</option>)}</select></label>
      <label className="monitor-request-filter">请求编号<input className="field" maxLength={128} placeholder="输入完整 request_id" value={filters.requestId} onChange={e => setFilters({ ...filters, requestId: e.target.value })} /></label>
      <button className="button" disabled={loading} type="submit">筛选</button>
    </form>
    {error && <div className="notice" role="alert">{error} <button className="button button-secondary" onClick={() => refresh()}>重试</button></div>}
    <div aria-busy={loading} className="monitor-summary">
      <div className="stat-card"><span className="stat-label">请求尝试</span><div className="stat-value">{overview ? count(overview.total) : "—"}</div><div className="stat-note">{overview ? `已结束 ${count(overview.finished)} · 运行中 ${count(overview.running)}` : "正在读取"}</div></div>
      <div className="stat-card"><span className="stat-label">正常返回率</span><div className="stat-value">{overview?.normal_return_rate != null ? `${(overview.normal_return_rate * 100).toFixed(1)}%` : "—"}</div><div className="stat-note">正常返回 / 已结束尝试（含取消）</div></div>
      <div className="stat-card"><span className="stat-label">请求耗时 P50 / P95</span><div className="monitor-latency">{duration(overview?.p50_ms)} <span>/ {duration(overview?.p95_ms)}</span></div><div className="stat-note">已结束尝试 · nearest-rank</div></div>
      <div className="stat-card"><span className="stat-label">已报告 Token</span><div className="stat-value">{overview ? count(metrics.total_tokens) : "—"}</div><div className="stat-note">{overview ? tokenCoverage(metrics) : "正在读取"}</div></div>
    </div>
    {overview && <><div className="monitor-health"><span>异常结束 <b>{count(overview.error)}</b></span><span>取消 <b>{count(overview.cancelled)}</b></span><span>长时间未结束 <b>{count(overview.incomplete)}</b></span><span>模型错误 <b>{count(metrics.model_errors)}</b> / {count(metrics.model_calls)}</span><span>工具错误 <b>{count(metrics.tool_errors)}</b> / {count(metrics.tool_calls)}</span><span>修复 / 降级 <b>{count(metrics.repair_count)} / {count(metrics.fallback_count)}</b></span></div><p className="trace-note">正常返回不等于所有任务完成；请结合业务结果和工具错误查看。缺报 Token 未估算，不折算费用。同一请求重试按不同追踪分别计数。</p>{!!Object.keys(overview.outcomes).length && <div className="monitor-outcomes">{Object.entries(overview.outcomes).map(([name, value]) => <span key={name}>{outcomeLabel[name] ?? name} <b>{value}</b></span>)}</div>}</>}
    <section className="panel monitor-requests"><div className="panel-header"><h2>请求记录</h2><span>{updatedAt ? `更新于 ${updatedAt}` : "尚未更新"}</span></div>
      {loading ? <div className="panel-body" role="status">正在加载追踪数据…</div> : list?.items.length ? <div className="monitor-table-wrap"><table className="monitor-table"><thead><tr><th>开始时间</th><th>请求编号</th><th>状态 / 业务结果</th><th>耗时</th><th>模型 / 工具</th><th>修复 / 降级</th><th>详情</th></tr></thead><tbody>{list.items.map(row => <tr key={row.trace_id} className={selected === row.trace_id ? "is-selected" : ""}>
        <td><time dateTime={row.started_at}>{dateTime(row.started_at)}</time></td><td><button className="monitor-id" title={row.request_id} onClick={() => choose(row.trace_id)}>{row.request_id}</button><small className="monitor-trace-id" title={row.trace_id}>{row.trace_id}</small></td>
        <td><span className={`trace-badge trace-${row.status}`}>{statusLabel[row.status] ?? row.status}</span><small>{outcomeLabel[row.outcome ?? "unspecified"] ?? row.outcome}</small></td><td>{duration(row.duration_ms)}</td><td>{count(row.metrics.model_calls)} / {count(row.metrics.tool_calls)}</td><td>{count(row.metrics.repair_count)} / {count(row.metrics.fallback_count)}</td><td><button className="monitor-detail-button" aria-label={`查看请求 ${row.request_id} 的详情`} onClick={() => choose(row.trace_id)}>查看 →</button></td>
      </tr>)}</tbody></table></div> : !error && <div className="empty-state"><strong>暂无符合条件的追踪记录</strong><p>先在问答工作台发起一次请求，再刷新。启用持久化前的历史日志不会自动补入。</p></div>}
      {!!list?.total && <div className="monitor-pagination"><span>共 {count(list.total)} 条 · 第 {page} / {Math.ceil(list.total / list.page_size)} 页</span><div><button className="button button-secondary" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button><button className="button button-secondary" disabled={loading || page * list.page_size >= list.total} onClick={() => setPage(page + 1)}>下一页</button></div></div>}
    </section>
    {selected && <section className="panel monitor-detail-panel" ref={detailRef}><div className="panel-header"><h2>请求执行详情</h2><button className="monitor-detail-button" onClick={() => choose("")}>关闭详情</button></div><div className="panel-body">{detailError ? <p className="notice" role="alert">{detailError}</p> : detail ? <TraceDetails trace={detail} /> : <p role="status">正在加载请求详情…</p>}</div></section>}
  </main>;
}
