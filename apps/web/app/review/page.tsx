"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ReviewCardItem from "../../components/ReviewCardItem";
import { errorMessage, request } from "../../lib/api";
import { cardStatusLabel, type CardStatus, type ReviewCard } from "../../lib/review-cards";

type StatusFilter = CardStatus | "all";
type Course = { id: string; name: string };

export default function KnowledgePage() {
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [courseQuery, setCourseQuery] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [courseMenuOpen, setCourseMenuOpen] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const course = params.get("course");
    const status = params.get("status");
    if (course) setSelectedCourseId(course);
    if (status === "new" || status === "review" || status === "mastered") setStatusFilter(status);
  }, []);

  useEffect(() => {
    Promise.all([request<ReviewCard[]>("/review-cards"), request<Course[]>("/courses")])
      .then(([items, availableCourses]) => { setCards(items); setCourses(availableCourses); })
      .catch((error) => setMessage(errorMessage(error)))
      .finally(() => setLoading(false));
  }, []);

  async function review(card: ReviewCard, status: CardStatus) {
    const updated = await request<ReviewCard>(`/review-cards/${card.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    setCards((current) => current.map((item) => item.id === card.id ? updated : item));
  }

  const statusCards = statusFilter === "all" ? cards : cards.filter((card) => card.status === statusFilter);
  const selectedCourse = courses.find((course) => course.id === selectedCourseId);
  const matchingCourses = courses.filter((course) => course.name.toLocaleLowerCase().includes(courseQuery.trim().toLocaleLowerCase()));
  const visibleCards = statusCards.filter((card) => selectedCourseId ? card.course_id === selectedCourseId : card.course_name.toLocaleLowerCase().includes(courseQuery.trim().toLocaleLowerCase()));
  const groups = Array.from(visibleCards.reduce<Map<string, { id: string; name: string; items: ReviewCard[] }>>((result, card) => {
    const group = result.get(card.course_id);
    if (group) group.items.push(card);
    else result.set(card.course_id, { id: card.course_id, name: card.course_name, items: [card] });
    return result;
  }, new Map()).values()).sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));

  return <main className="content review-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">◷</span><div className="page-hero-copy"><div className="eyebrow">课后整理</div><h1>知识点清单</h1><p>按课程保存知识点，看过后标记需要复习或已掌握。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href="/">返回课程库</Link></div></section>
    {message && <div className="notice review-notice" role="alert">{message}</div>}
    <section className="panel">
      <div className="panel-header"><h2>课程知识点</h2><span>{loading ? "加载中" : `共 ${cards.length} 张`}</span></div>
      <div className="panel-body">{loading ? <p role="status">正在加载知识点…</p> : courses.length ? <>
        <div className="review-course-filter">
          <div className="review-filter-course" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setCourseMenuOpen(false); }}>
            <label htmlFor="review-course-search">筛选课程</label>
            <input id="review-course-search" className="field" type="search" role="combobox" aria-autocomplete="list" aria-expanded={courseMenuOpen} aria-controls="review-course-menu" placeholder="全部课程 · 点击选择或搜索" value={selectedCourse?.name ?? courseQuery} onFocus={(event) => { setCourseMenuOpen(true); if (selectedCourseId) event.currentTarget.select(); }} onChange={(event) => { setSelectedCourseId(""); setCourseQuery(event.target.value); setCourseMenuOpen(true); }} onKeyDown={(event) => { if (event.key === "Escape") setCourseMenuOpen(false); }} />
            {courseMenuOpen && <div className="review-course-menu" id="review-course-menu" role="listbox" aria-label="课程列表">
              <button type="button" role="option" aria-selected={!selectedCourseId && !courseQuery} onClick={() => { setSelectedCourseId(""); setCourseQuery(""); setCourseMenuOpen(false); }}>全部课程</button>
              {matchingCourses.map((course) => <button type="button" role="option" aria-selected={selectedCourseId === course.id} key={course.id} onClick={() => { setSelectedCourseId(course.id); setCourseQuery(""); setCourseMenuOpen(false); }}>{course.name}</button>)}
              {!matchingCourses.length && <p>没有匹配的课程</p>}
            </div>}
          </div>
          <div className="review-filter-status">
            <span className="review-filter-label">掌握状态</span>
            <div className="review-status-filter" role="group" aria-label="掌握状态">{(["all", "new", "review", "mastered"] as StatusFilter[]).map((status) => <button type="button" key={status} className={statusFilter === status ? "active" : ""} aria-pressed={statusFilter === status} onClick={() => setStatusFilter(status)}>{status === "all" ? "全部状态" : cardStatusLabel[status]}</button>)}</div>
          </div>
        </div>
        {groups.length ? <div className="review-course-list">{groups.map((group) => <section className="review-course-group" key={group.id}><div className="review-course-heading"><div><span className="eyebrow">课程</span><h3><Link href={`/courses/${group.id}`}>{group.name} ↗</Link></h3></div><span>{group.items.length} 张卡片</span></div><div className="review-card-grid">{group.items.map((card) => <ReviewCardItem key={card.id} card={card} onReview={review} showLesson />)}</div></section>)}</div> : <div className="review-course-empty"><strong>{cards.length ? "没有符合条件的知识点" : "还没有知识点"}</strong><p>{cards.length ? "试试其他课程或掌握状态。" : "可以在课次的“智能纪要 → 复习卡片”中创建。"}</p></div>}
      </> : <div className="empty-state"><div className="empty-icon">✓</div><strong>还没有知识点</strong><p>可以在课次的“智能纪要 → 复习卡片”中创建。</p><Link className="button button-secondary" href="/">查看课程</Link></div>}</div>
    </section>
  </main>;
}
