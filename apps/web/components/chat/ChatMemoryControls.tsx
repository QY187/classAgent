"use client";
import Link from "next/link";
import { useEffect,useState } from "react";
import { request,errorMessage } from "../../lib/api";
export default function ChatMemoryControls({conversationId,disabled}:{conversationId:string;disabled:boolean}){
 const [revision,setRevision]=useState(0);
 const [temporary,setTemporary]=useState<boolean|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
 useEffect(()=>{let active=true;setTemporary(null);setError("");request<{temporary:boolean}>(`/chat/conversations/${conversationId}/memory-policy`).then(r=>{if(active)setTemporary(r.temporary);}).catch(e=>{if(active)setError(errorMessage(e));});return()=>{active=false;};},[conversationId,revision]);
 return <details className="chat-memory-controls"><summary>记忆{temporary?" · 临时模式":""}</summary><div style={{padding:12,maxWidth:360}}><label><input type="checkbox" checked={temporary??false} disabled={disabled||busy||temporary===null} onChange={e=>{const value=e.target.checked;setBusy(true);setError("");request<{temporary:boolean}>(`/chat/conversations/${conversationId}/memory-policy`,{method:"PATCH",body:JSON.stringify({temporary:value})}).then(r=>setTemporary(r.temporary)).catch(e=>setError(errorMessage(e))).finally(()=>setBusy(false));}}/> 当前对话使用临时模式</label><p>停止历史召回、摘要和长期记忆读写。当前对话的近期问答及聊天记录仍保留。</p>{error&&<p role="alert">{error} <button disabled={busy||disabled} onClick={()=>setRevision(v=>v+1)}>重试</button></p>}<Link href="/memories">管理记忆与全局设置</Link></div></details>;
}
