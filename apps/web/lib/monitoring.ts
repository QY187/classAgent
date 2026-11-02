export type TraceEvent = {
  event: string; timestamp: string; name?: string; kind?: string; span_id?: string;
  parent_span_id?: string; status?: string; duration_ms?: number; tool?: string;
  provider?: string; model?: string; reason?: string; error_type?: string; error_code?: string;
  db_queries?: number; prompt_tokens?: number; completion_tokens?: number; total_tokens?: number;
  usage_reported?: boolean; strategy?: string; candidate_limit?: number; selected_count?: number;
};
export type Trace = {
  trace_id: string; request_id: string; conversation_id: string; started_at: string;
  finished_at: string | null; status: string; outcome: string | null; duration_ms: number | null;
  metrics: Record<string, number>; dropped_events: number;
  attributes?: Record<string, string | number | boolean | null>; events?: TraceEvent[];
};
export type TraceList = { total: number; page: number; page_size: number; items: Trace[] };
export type Overview = {
  total: number; finished: number; ok: number; error: number; cancelled: number;
  running: number; incomplete: number; normal_return_rate: number | null;
  metrics: Record<string, number>; p50_ms: number | null; p95_ms: number | null;
  outcomes: Record<string, number>;
};
export const statusLabel: Record<string, string> = {
  ok: "正常返回", error: "异常结束", cancelled: "已取消", running: "运行中", incomplete: "长时间未结束",
};
export const outcomeLabel: Record<string, string> = {
  answered: "已回答", needs_input: "等待补充", insufficient_evidence: "依据不足", completed: "已完成",
  partially_completed: "部分完成", failed: "失败", rejected: "请求被拒绝", cancelled: "已取消", replayed: "幂等重放",
  unspecified: "未标记",
};
export function duration(ms: number | null | undefined) {
  return ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}
export function dateTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}
export function count(value: number | undefined) { return (value ?? 0).toLocaleString("zh-CN"); }
export function tokenCoverage(metrics: Record<string, number>) {
  return metrics.model_calls ? `${count(metrics.total_tokens_reported_calls)}/${count(metrics.model_calls)} 次调用报告总量` : "暂无模型调用";
}

export function orderedStages(events: TraceEvent[]): { event: TraceEvent; depth: number }[] {
  const spans = events.filter(event => event.event === "span.finished" && event.span_id);
  const byId = new Map(spans.map(event => [event.span_id!, event]));
  const children = new Map<string | undefined, TraceEvent[]>();
  for (const event of spans) {
    const parent = event.parent_span_id && byId.has(event.parent_span_id) ? event.parent_span_id : undefined;
    children.set(parent, [...(children.get(parent) ?? []), event]);
  }
  const start = (event: TraceEvent) => Date.parse(event.timestamp) - (event.duration_ms ?? 0);
  for (const siblings of children.values()) siblings.sort((a, b) => start(a) - start(b));
  const visited = new Set<string>();
  const result: { event: TraceEvent; depth: number }[] = [];
  function visit(event: TraceEvent, depth: number) {
    if (visited.has(event.span_id!)) return;
    visited.add(event.span_id!); result.push({ event, depth: Math.min(depth, 6) });
    for (const child of children.get(event.span_id) ?? []) visit(child, depth + 1);
  }
  for (const event of children.get(undefined) ?? []) visit(event, 0);
  // 截断或损坏的数据也应可展示，不能因循环引用卡住页面。
  for (const event of spans) visit(event, 0);
  return result;
}

export const stageLabel: Record<string, string> = {
  request: "请求总览", "intent.context": "读取对话范围", "intent.plan": "规划用户意图",
  "intent.resolve": "解析与校验意图", "agent.execute": "执行任务", "agent.round": "工具决策轮次",
  "tool.dispatch": "分发工具", "tool.execute": "执行工具", "model.chat": "对话模型调用",
  "model.embedding": "向量模型调用", "model.rerank": "重排模型调用", "model.quiz": "小测模型调用",
  "rag.retrieve": "检索课堂内容", "rag.rewrite": "改写查询", "rag.load_candidates": "加载授权候选",
  "rag.vector_recall": "向量召回", "rag.bm25": "BM25 召回", "rag.fusion": "融合候选",
  "rag.rerank": "候选重排", "rag.keyword_fallback": "关键词回退",
  "answer.validate": "校验最终回答", "answer.compose": "组装回答", "request.persist": "保存结果",
  "request.fail_persist": "保存失败状态",
};
