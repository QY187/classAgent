"use client";
import { useRef, useState } from "react";
import { errorMessage, request } from "../../lib/api";
import { dateTime, type Trace } from "../../lib/monitoring";
import TraceDetails from "../monitoring/TraceDetails";

export default function ChatRequestTrace({ requestId, conversationId }: { requestId: string; conversationId: string }) {
  const [items, setItems] = useState<Trace[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);
  async function load() {
    if (busy.current) return;
    busy.current = true; setLoading(true); setError("");
    try {
      const result = await request<{ items: Trace[] }>(`/monitoring/requests/${encodeURIComponent(requestId)}?conversation_id=${encodeURIComponent(conversationId)}`);
      setItems(result.items); setSelected(0);
    } catch (err) { setError(errorMessage(err)); }
    finally { busy.current = false; setLoading(false); }
  }
  return <details className="chat-request-trace" onToggle={event => { if (event.currentTarget.open && items === null) void load(); }}>
    <summary>查看请求执行详情</summary>
    <div className="chat-trace-toolbar"><button className="monitor-detail-button" disabled={loading} onClick={() => void load()}>刷新追踪</button>{items && items.length > 1 && <label>执行尝试 <select aria-label="选择执行尝试" value={selected} onChange={e => setSelected(Number(e.target.value))}>{items.map((trace, index) => <option value={index} key={trace.trace_id}>{dateTime(trace.started_at)}{index === 0 ? " · 最新" : ""}</option>)}</select></label>}</div>
    {loading ? <p role="status">正在读取追踪记录…</p> : error ? <p role="status">{error}。旧消息可能没有追踪，或记录尚未落库，可稍后刷新。</p> : items?.[selected] && <TraceDetails trace={items[selected]} compact />}
  </details>;
}
