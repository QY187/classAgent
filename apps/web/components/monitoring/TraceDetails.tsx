"use client";

import { count, dateTime, duration, orderedStages, outcomeLabel, stageLabel, statusLabel, tokenCoverage, type Trace } from "../../lib/monitoring";
import "./monitoring.css";

export default function TraceDetails({ trace, compact = false }: { trace: Trace; compact?: boolean }) {
  const metrics = trace.metrics;
  const events = trace.events ?? [];
  const spans = orderedStages(events);
  const notices = events.filter(event => !["request.started", "request.finished", "span.finished"].includes(event.event));
  return <div className={`trace-detail${compact ? " trace-compact" : ""}`}>
    <div className="trace-heading"><span className={`trace-badge trace-${trace.status}`}>{statusLabel[trace.status] ?? trace.status}</span><strong>{outcomeLabel[trace.outcome ?? "unspecified"] ?? trace.outcome}</strong><span>{duration(trace.duration_ms)}</span></div>
    <dl className="trace-identifiers"><div><dt>请求编号</dt><dd>{trace.request_id}</dd></div><div><dt>追踪编号</dt><dd>{trace.trace_id}</dd></div><div><dt>开始时间</dt><dd>{dateTime(trace.started_at)}</dd></div></dl>
    {trace.finished_at && <><div className="trace-metrics">
      <div><span>模型调用 / 错误</span><strong>{count(metrics.model_calls)} / {count(metrics.model_errors)}</strong></div>
      <div><span>工具调用 / 错误</span><strong>{count(metrics.tool_calls)} / {count(metrics.tool_errors)}</strong></div>
      <div><span>修复 / 降级</span><strong>{count(metrics.repair_count)} / {count(metrics.fallback_count)}</strong></div>
      <div><span>SQL 次数 / 错误</span><strong>{count(metrics.db_queries)} / {count(metrics.db_errors)}</strong></div>
    </div>
    <p className="trace-note">已报告 Token：{count(metrics.total_tokens)}（输入 {count(metrics.prompt_tokens)}，输出 {count(metrics.completion_tokens)}）；{tokenCoverage(metrics)}。缺报部分未估算。SQL 执行累计 {duration(metrics.db_duration_ms)}。</p></>}
    {trace.attributes?.retry === true && <p className="trace-note">本次为用户重试，工具和模型计数仅统计这次尝试。</p>}
    {trace.dropped_events > 0 && <p className="notice">阶段事件超过保存上限，省略 {count(trace.dropped_events)} 条；请求汇总指标仍然完整。</p>}
    {!trace.finished_at && <p className="trace-note">尚无结束记录。运行中或进程中断的请求需结合业务状态排查；刷新后可查看最新状态。</p>}
    {!!spans.length && <><h3>执行阶段</h3><p className="trace-note">父阶段耗时包含子阶段，不能直接相加。点击阶段可查看模型、工具和错误码。</p><ol className="trace-stages">{spans.map(({ event, depth }) => <li key={event.span_id} style={{ paddingInlineStart: `${depth * (compact ? 10 : 18)}px` }}>
      <details><summary><span className={`trace-stage-dot ${event.status === "error" ? "is-error" : ""}`} /><span className="trace-stage-title">{stageLabel[event.name ?? ""] ?? event.name}<small>{event.tool ?? event.model ?? event.name}</small></span><span className="trace-stage-time">{duration(event.duration_ms)}</span>{event.status === "error" && <span className="trace-error-label">异常</span>}</summary>
      <dl className="trace-event-fields">{Object.entries(event).filter(([key]) => ["provider", "model", "tool", "error_type", "error_code", "strategy", "candidate_limit", "selected_count", "db_queries", "prompt_tokens", "completion_tokens", "total_tokens"].includes(key)).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}{event.kind === "model" && !event.usage_reported && <div><dt>用量</dt><dd>供应商未报告</dd></div>}</dl></details>
    </li>)}</ol></>}
    {!!notices.length && <><h3>修复、降级与状态事件</h3><ul className="trace-notices">{notices.map((event, index) => <li key={index}><code>{event.event}</code><span>{event.reason ?? event.error_code ?? "已记录"}</span></li>)}</ul></>}
  </div>;
}
