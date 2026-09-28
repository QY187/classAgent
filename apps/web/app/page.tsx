"use client";

import { ChangeEvent, FormEvent, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [courseId, setCourseId] = useState("");
  const [lessonId, setLessonId] = useState("");
  const [courseName, setCourseName] = useState("数据结构");
  const [lessonTitle, setLessonTitle] = useState("第 1 讲");
  const [message, setMessage] = useState("先创建课程和课次，再上传音频。");

  async function createCourse(event: FormEvent) {
    event.preventDefault();
    const response = await fetch(`${apiUrl}/courses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: courseName }),
    });
    const data = await response.json();
    if (!response.ok) return setMessage(data.detail ?? "创建课程失败");
    setCourseId(data.id);
    setMessage(`课程已创建：${data.id}`);
  }

  async function createLesson(event: FormEvent) {
    event.preventDefault();
    if (!courseId) return setMessage("请先创建课程");
    const response = await fetch(`${apiUrl}/courses/${courseId}/lessons`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: lessonTitle }),
    });
    const data = await response.json();
    if (!response.ok) return setMessage(data.detail ?? "创建课次失败");
    setLessonId(data.id);
    setMessage(`课次已创建：${data.id}`);
  }

  async function uploadAudio(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !lessonId) return setMessage("请先创建课次");
    const formData = new FormData();
    formData.append("file", file);
    setMessage("正在上传音频…");
    const response = await fetch(`${apiUrl}/lessons/${lessonId}/audio`, { method: "POST", body: formData });
    const data = await response.json();
    setMessage(response.ok ? `上传成功，任务已加入队列：${data.id}` : (data.detail ?? "上传失败"));
  }

  return (
    <main style={{ maxWidth: 720, margin: "48px auto", fontFamily: "sans-serif", padding: 24 }}>
      <h1>ClassAgent 技术验证版</h1>
      <p>验证流程：创建课程 → 创建课次 → 上传音频 → 异步处理。</p>
      <form onSubmit={createCourse} style={{ display: "flex", gap: 8, marginTop: 24 }}>
        <input value={courseName} onChange={(event) => setCourseName(event.target.value)} aria-label="课程名称" />
        <button type="submit">创建课程</button>
      </form>
      <form onSubmit={createLesson} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input value={lessonTitle} onChange={(event) => setLessonTitle(event.target.value)} aria-label="课次标题" />
        <button type="submit">创建课次</button>
      </form>
      <label style={{ display: "block", marginTop: 24 }}>
        上传音频
        <input type="file" accept="audio/*" onChange={uploadAudio} style={{ display: "block", marginTop: 8 }} />
      </label>
      <p style={{ marginTop: 24, color: "#555" }}>{message}</p>
      <small>当前默认使用 mock 转写服务，接入真实 ASR 后会替换模拟结果。</small>
    </main>
  );
}

