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

  return <main className="content review-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">◷</span><div className="page-hero-copy"><div className="eyebrow">课后复习</div><h1>今日复习</h1><p>回顾已到期的课堂卡片，选一个掌握状态安排下一次复习。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href="/">返回课程库</Link></div></section>
    {message && <div className="notice review-notice" role="alert">{message}</div>}
    <section className="panel"><div className="panel-header"><h2>待复习卡片</h2><span>{loading ? "加载中" : `${cards.length} 张待复习${completed ? ` · 已完成 ${completed} 张` : ""}`}</span></div><div className="panel-body">{loading ? <p role="status">正在加载今日复习…</p> : cards.length ? <div className="review-card-grid">{cards.map((card) => <ReviewCardItem key={card.id} card={card} onReview={review} />)}</div> : <div className="empty-state"><div className="empty-icon">✓</div><strong>今天的卡片已复习完</strong><p>新卡片可以在课次的“智能纪要 → 复习卡片”中创建。</p><Link className="button button-secondary" href="/">查看课程</Link></div>}</div></section>
  </main>;
}
