"use client";
import { useEffect, useRef, useState } from "react";

export default function ChatCopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const text = useRef<HTMLTextAreaElement>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  async function copy() {
    if (busy) return;
    setBusy(true); setCopied(false); setManual(false);
    if (timer.current) clearTimeout(timer.current);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(content);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch { setManual(true); }
    finally { setBusy(false); }
  }
  return <div className="chat-copy-control"><button type="button" className="chat-copy-button" aria-label="复制回答" title="复制回答" disabled={busy} onClick={copy}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4" /></svg>
    <span aria-live="polite">{copied ? "已复制" : busy ? "复制中…" : "复制"}</span>
  </button>{manual && <div className="chat-copy-manual"><p role="status">浏览器未允许自动复制，请选中文字后按 Ctrl+C（Mac 使用 ⌘C）。</p><textarea ref={text} readOnly value={content} aria-label="手动复制回答" onFocus={event => event.currentTarget.select()} /><button type="button" className="button button-quiet" onClick={() => { text.current?.focus(); text.current?.select(); }}>全选文本</button><button type="button" className="button button-quiet" onClick={() => setManual(false)}>关闭</button></div>}</div>;
}
