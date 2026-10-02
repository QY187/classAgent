"use client";
import { useState } from "react";
import { errorMessage, request } from "../lib/api";
import { recycledKey, type RecycledItem } from "../lib/recycle-bin";
import PermanentDeleteDialog from "./PermanentDeleteDialog";

export default function RecycleBinPurge({ item, disabled, onBusyChange, onDeleted }: {
  item: RecycledItem; disabled: boolean; onBusyChange: (busy: boolean) => void;
  onDeleted: (pending: number) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function purge() {
    if (busy) return;
    setBusy(true); onBusyChange(true); setError("");
    try {
      const result = await request<{ pending: number }>(`/recycle-bin/${recycledKey(item)}`, { method: "DELETE" });
      setOpen(false);
      window.dispatchEvent(new Event("classagent:file-cleanup-updated"));
      await onDeleted(result.pending);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); onBusyChange(false); }
  }
  return <><button className="button recycle-purge-button" disabled={disabled} onClick={() => { setOpen(true); setError(""); }}>彻底删除</button>{open && <PermanentDeleteDialog item={item} busy={busy} error={error} onCancel={() => setOpen(false)} onConfirm={purge} />}</>;
}
