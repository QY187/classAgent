"use client";
import { useState } from "react";
import type { AgentStep, ChatMessage } from "../../lib/chat";

export default function ChatAgentSteps({ steps, status, generating }: { steps: AgentStep[]; status: ChatMessage["status"]; generating: boolean }) {
  const [expanded, setExpanded] = useState<boolean | null>(null);
  if (!steps.length) return null;
  const active = status === "pending" && generating;
  const failed = steps.filter((step) => step.status === "failed").length;
  const completed = steps.filter((step) => step.status === "completed").length;
  const running = steps.find((step) => step.status === "running");
  const heading = active ? running ? `正在${running.label}…` : "正在整理回答…" : status === "cancelled" ? `已停止 · 完成 ${completed} 个步骤` : status === "failed" || status === "pending" ? `回答中断 · 完成 ${completed} 个步骤` : failed ? `完成 ${completed} 个步骤 · ${failed} 个步骤失败` : `已完成 ${completed} 个步骤`;
  return <section className={`chat-agent-steps${active ? " active" : ""}`} aria-label="工具执行过程">
    <button type="button" className="chat-agent-summary" aria-expanded={expanded ?? active} onClick={() => setExpanded(!(expanded ?? active))}><span aria-hidden="true">{active ? "◌" : "◇"}</span><span role={active ? "status" : undefined}>{heading}</span><svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m6 4 4 4-4 4"/></svg></button>
    {(expanded ?? active) && <ol>{steps.map((step) => { const interrupted = step.status === "running" && !active; const label = interrupted ? "已中断" : step.status === "running" ? "进行中" : step.status === "completed" ? "已完成" : "失败"; return <li key={step.id} className={interrupted ? "interrupted" : step.status}><span aria-hidden="true">{interrupted ? "−" : step.status === "completed" ? "✓" : step.status === "failed" ? "!" : "◌"}</span><div><span>{step.label}</span>{step.error && <p>{step.error}</p>}</div><small>{label}</small></li>; })}</ol>}
  </section>;
}
