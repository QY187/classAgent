"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ReviewCardItem from "../../components/ReviewCardItem";
import { errorMessage, request } from "../../lib/api";
import { type CardStatus, type ReviewCard } from "../../lib/review-cards";

export default function TodayReviewPage() {
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [completed, setCompleted] = useState(0);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [courseQuery, setCourseQuery] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");

  useEffect(() => {
    request<ReviewCard[]>("/review-cards/due")
      .then(setCards)
      .catch((error) => setMessage(errorMessage(error)))
      .finally(() => setLoading(false));
  }, []);

  async function review(card: ReviewCard, status: CardStatus) {
    const updated = await request<ReviewCard>(`/review-cards/${card.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    if (new Date(updated.next_review_at).getTime() > Date.now()) {
      setCards((current) => current.filter((item) => item.id !== card.id));
      setCompleted((count) => count + 1);
    } else {
      setCards((current) => current.map((item) => item.id === card.id ? updated : item));
    }
  }

  const groups = Array.from(cards.reduce<Map<string, { id: string; name: string; items: ReviewCard[] }>>((courses, card) => {
    const group = courses.get(card.course_id);
    if (group) group.items.push(card);
    else courses.set(card.course_id, { id: card.course_id, name: card.course_name, items: [card] });
    return courses;
  }, new Map()).values()).sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  const matchingGroups = groups.filter((group) => group.name.toLocaleLowerCase().includes(courseQuery.trim().toLocaleLowerCase()));
  const visibleGroups = selectedCourseId ? groups.filter((group) => group.id === selectedCourseId) : matchingGroups;

  return <main className="content review-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">◷</span><div className="page-hero-copy"><div className="eyebrow">课后复习</div><h1>今日复习</h1><p>回顾已到期的课堂卡片，选一个掌握状态安排下一次复习。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href="/">返回课程库</Link></div></section>
    {message && <div className="notice review-notice" role="alert">{message}</div>}
    <section className="panel"><div className="panel-header"><h2>按课程复习</h2><span>{loading ? "加载中" : `${cards.length} 张待复习${completed ? ` · 已完成 ${completed} 张` : ""}`}</span></div><div className="panel-body">{loading ? <p role="status">正在加载今日复习…</p> : groups.length ? <>
      <div className="review-course-filter"><label htmlFor="review-course-search">筛选课程</label><input id="review-course-search" className="field" type="search" placeholder="搜索课程名称" value={courseQuery} onChange={(event) => { setCourseQuery(event.target.value); setSelectedCourseId(""); }} /><div className="review-course-options" aria-label="选择课程"><button type="button" className={`review-course-option${!selectedCourseId && !courseQuery ? " active" : ""}`} aria-pressed={!selectedCourseId && !courseQuery} onClick={() => { setSelectedCourseId(""); setCourseQuery(""); }}>全部课程</button>{matchingGroups.map((group) => <button type="button" key={group.id} className={`review-course-option${selectedCourseId === group.id ? " active" : ""}`} aria-pressed={selectedCourseId === group.id} onClick={() => { setSelectedCourseId(group.id); setCourseQuery(""); }}>{group.name}<span>{group.items.length}</span></button>)}</div></div>
      {visibleGroups.length ? <div className="review-course-list">{visibleGroups.map((group) => <section className="review-course-group" key={group.id}><div className="review-course-heading"><div><span className="eyebrow">课程</span><h3><Link href={`/courses/${group.id}`}>{group.name} ↗</Link></h3></div><span>{group.items.length} 张待复习</span></div><div className="review-card-grid">{group.items.map((card) => <ReviewCardItem key={card.id} card={card} onReview={review} showLesson />)}</div></section>)}</div> : <p className="review-course-empty">没有找到匹配的课程。</p>}
    </> : <div className="empty-state"><div className="empty-icon">✓</div><strong>今天的卡片已复习完</strong><p>新卡片可以在课次的“智能纪要 → 复习卡片”中创建。</p><Link className="button button-secondary" href="/">查看课程</Link></div>}</div></section>
  </main>;
}
