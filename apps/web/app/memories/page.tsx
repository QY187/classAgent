"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { request, errorMessage } from "../../lib/api";
import "./memory.css";

type Memory={id:string;content:string;course_id:string|null;version:number;source_message_id:string|null;updated_at:string};
type Settings={history_enabled:boolean;long_term_enabled:boolean};
type Course={id:string;name:string};
export default function MemoriesPage(){
  const [items,setItems]=useState<Memory[]>([]),[settings,setSettings]=useState<Settings|null>(null),[courses,setCourses]=useState<Course[]>([]);
  const [error,setError]=useState(""),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[notice,setNotice]=useState("");
  const [text,setText]=useState(""),[courseId,setCourseId]=useState(""),[editing,setEditing]=useState<Memory|null>(null),[draft,setDraft]=useState("");
  const [source,setSource]=useState<{content:string;conversation_id:string}|null>(null);
  async function load(){setLoading(true);setError("");try{const [m,s,c]=await Promise.all([request<Memory[]>("/memories"),request<Settings>("/memory-settings"),request<Course[]>("/courses")]);setItems(m);setSettings(s);setCourses(c);}catch(e){setError(errorMessage(e));}finally{setLoading(false);}}
  useEffect(()=>{void load();},[]);
  async function action(work:()=>Promise<void>){if(busy)return;setBusy(true);setError("");setNotice("");try{await work();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  function changeSetting(key:keyof Settings,value:boolean){if(!settings)return;void action(async()=>{const updated=await request<Settings>("/memory-settings",{method:"PATCH",body:JSON.stringify({...settings,[key]:value})});setSettings(updated);setNotice("记忆设置已更新");});}
  function add(e:FormEvent){e.preventDefault();void action(async()=>{await request("/memories",{method:"POST",body:JSON.stringify({content:text,course_id:courseId||null})});setText("");await load();setNotice("已保存记忆");});}
  return <main className="content memory-page"><div className="page-heading"><span className="eyebrow">我的学习空间</span><h1>记忆管理</h1><p>管理你明确保存的学习偏好与目标。课程资料和学习记录仍以实际数据为准。</p></div>
    {error&&<p className="notice" role="alert">{error} <button onClick={()=>void load()} disabled={busy}>重新加载</button></p>}
    {notice&&<p role="status">{notice}</p>}
    {loading?<p role="status">正在加载记忆…</p>:settings&&<>
    <section className="panel memory-controls"><h2>记忆设置</h2><label><input type="checkbox" checked={settings.history_enabled} disabled={busy} onChange={e=>changeSetting("history_enabled",e.target.checked)}/> 从历史对话找回相关内容</label><p>关闭后停止摘要和跨对话召回，并清除派生摘要与向量索引；原聊天记录仍保留，当前对话近期问答仍可用于连续交流。</p>
    <label><input type="checkbox" checked={settings.long_term_enabled} disabled={busy} onChange={e=>changeSetting("long_term_enabled",e.target.checked)}/> 使用长期记忆</label><p>关闭后停止读取和新增长期记忆，已有条目仍可查看、编辑或删除。</p></section>
    <section className="panel"><h2>添加记忆</h2><form onSubmit={add} className="memory-form"><label>希望记住的内容<textarea className="field" required minLength={2} maxLength={300} value={text} onChange={e=>setText(e.target.value)} placeholder="例如：讲解算法时先给具体例子，再给代码"/></label><label>适用范围<select className="field" value={courseId} onChange={e=>setCourseId(e.target.value)}><option value="">所有对话</option>{courses.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button className="button button-primary" disabled={busy||!settings.long_term_enabled}>保存记忆</button></form><p>也可以在问答中发送“记住：内容”“忘记：完整内容”或“修改记忆：原内容 =&gt; 新内容”。课程对话默认只记在该课程；“全局记住：内容”适用于其他对话。</p></section>
    <section className="memory-list" aria-label="已保存的记忆"><h2>已保存的记忆 · {items.length}</h2>{!items.length&&<div className="panel"><p>还没有长期记忆。只有你明确保存的内容才会显示在这里。</p></div>}
    {items.map(item=><article className="panel memory-card" key={item.id}><span className="eyebrow">{item.course_id?courses.find(c=>c.id===item.course_id)?.name||"指定课程":"所有对话"}</span>{editing?.id===item.id?<form onSubmit={e=>{e.preventDefault();void action(async()=>{await request(`/memories/${item.id}`,{method:"PATCH",body:JSON.stringify({content:draft,version:item.version})});setEditing(null);await load();setNotice("已更新，旧内容停止使用");});}}><label>修改记忆<textarea className="field" required minLength={2} maxLength={300} value={draft} onChange={e=>setDraft(e.target.value)}/></label><div className="memory-actions"><button className="button button-primary" disabled={busy}>保存修改</button><button type="button" className="button button-secondary" disabled={busy} onClick={()=>setEditing(null)}>取消</button></div></form>:<p>{item.content}</p>}<small>{new Date(item.updated_at).toLocaleString("zh-CN")}</small><div className="memory-actions"><button disabled={busy} onClick={()=>{setEditing(item);setDraft(item.content);}}>编辑</button>{item.source_message_id&&<button disabled={busy} onClick={()=>void action(async()=>{setSource(await request(`/memory-sources/${item.source_message_id}`));})}>查看来源</button>}<button disabled={busy} onClick={()=>{if(window.confirm("删除这条长期记忆？原聊天记录仍保留。"))void action(async()=>{await request(`/memories/${item.id}`,{method:"DELETE"});await load();setNotice("已删除记忆");});}}>删除</button></div></article>)}</section>
    </>}{source&&<section className="panel memory-source" aria-label="记忆来源"><h2>原始消息</h2><p>{source.content}</p><div className="memory-actions"><Link href={`/chat?conversation=${encodeURIComponent(source.conversation_id)}`}>打开来源对话</Link><button onClick={()=>setSource(null)}>关闭</button></div></section>}
  </main>;
}
