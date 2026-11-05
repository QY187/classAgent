"use client";
import { useId } from "react";
import type { AgentModel } from "../../lib/chat";

export default function ChatModelSelect({ models, value, onChange, loading, error, disabled, onRetry }: {
  models: AgentModel[]; value: string; onChange: (id: string) => void; loading: boolean;
  error: string; disabled: boolean; onRetry: () => void;
}) {
  const id = useId();
  const selected = models.find((model) => model.id === value);
  return <div className="chat-model-control">
    <label htmlFor={id}>模型</label>
    <select id={id} aria-label="选择 Agent 模型" value={value} onChange={(event) => onChange(event.target.value)}
      disabled={disabled || loading || !!error || !models.length} aria-describedby={error ? `${id}-error` : undefined}>
      {loading ? <option value={value}>读取模型…</option> : <>
        {!selected && <option value={value} disabled>{models.length ? "原模型不可用，请选择" : "没有可用模型"}</option>}
        {models.map((model) => <option key={model.id} value={model.id} disabled={!model.available}>
          {model.label}{model.available ? "" : "（未配置）"}
        </option>)}
      </>}
    </select>
    {error && <div id={`${id}-error`} className="chat-model-error" role="alert">{error}<button type="button" disabled={disabled || loading} onClick={onRetry}>重试</button></div>}
  </div>;
}
