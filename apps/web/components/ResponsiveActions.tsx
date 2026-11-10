"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** 桌面直接展示操作，手机折叠次要操作，保持同一份按钮与业务状态。 */
export default function ResponsiveActions({ children, label = "更多操作" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) { setOpen(false); trigger.current?.focus(); }
    };
    const focusOutside = (event: FocusEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    document.addEventListener("focusin", focusOutside);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      document.removeEventListener("focusin", focusOutside);
    };
  }, [open]);
  return <div ref={root} className={`responsive-actions${open ? " is-open" : ""}`}>
    <button ref={trigger} className="button button-secondary responsive-actions-toggle" type="button" aria-label={label} aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>更多 <span aria-hidden="true">···</span></button>
    <div id={id} className="responsive-actions-items">{children}</div>
  </div>;
}
