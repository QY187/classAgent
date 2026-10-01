"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ReviewCardItem from "../../../../components/ReviewCardItem";
import { errorMessage, request } from "../../../../lib/api";
import { type CardStatus, type CardType, type ReviewCard } from "../../../../lib/review-cards";

type Lesson = { id: string; title: string; course_id: string };

export default function LessonReviewPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [cardType, setCardType] = useState<CardType>("concept");

  async function reloadCards() {
    setCards(await request<ReviewCard[]>(`/lessons/${lessonId}/review-cards`));
  }

  useEffect(() => {
    Promise.all([request<Lesson>(`/lessons/${lessonId}`), request<ReviewCard[]>(`/lessons/${lessonId}/review-cards`)])
      .then(([nextLesson, nextCards]) => { setLesson(nextLesson); setCards(nextCards); })
      .catch((error) => setMessage(errorMessage(error)))
      .finally(() => setLoading(false));
  }, [lessonId]);

  async function generate() {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await request<{ created: number; skipped: number }>(`/lessons/${lessonId}/review-cards/from-summary`, { method: "POST" });
      await reloadCards();
      setMessage(result.created ? `已生成 ${result.created} 张有原文依据的卡片。` : "没有新增卡片；已有概念不会重复生成，缺少来源的概念会跳过。");
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !body.trim() || busy) return;
    setBusy(true); setMessage("");
    try {
      const card = await request<ReviewCard>(`/lessons/${lessonId}/review-cards`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim(), body: body.trim(), card_type: cardType }) });
      setCards((current) => [card, ...current]);
      setTitle(""); setBody(""); setAdding(false);
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function review(card: ReviewCard, status: CardStatus) {
    const updated = await request<ReviewCard>(`/review-cards/${card.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    setCards((current) => current.map((item) => item.id === card.id ? updated : item));
  }

  async function save(card: ReviewCard, changes: { title: string; body: string; card_type: CardType }) {
    const updated = await request<ReviewCard>(`/review-cards/${card.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
    setCards((current) => current.map((item) => item.id === card.id ? updated : item));
  }

  async function remove(card: ReviewCard) {
    await request(`/review-cards/${card.id}`, { method: "DELETE" });
    setCards((current) => current.filter((item) => item.id !== card.id));
  }

  if (loading) return <main className="content"><p role="status">正在加载复习卡片…</p></main>;
  if (!lesson) return <main className="content"><div className="notice">{message || "课次不存在"}</div></main>;
  return <main className="content review-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">▤</span><div className="page-hero-copy"><div className="eyebrow">课后复习</div><h1>复习卡片</h1><p>{lesson.title} · 把课堂重点变成可以反复回顾的卡片</p></div><div className="page-hero-actions"><Link className="button button-secondary" href={`/lessons/${lessonId}/summary`}>查看纪要</Link><button className="button button-secondary" type="button" onClick={() => setAdding((value) => !value)}>手动新增</button><button className="button button-primary" type="button" onClick={generate} disabled={busy}>从纪要生成</button></div></section>
    {message && <div className="notice review-notice" role="status">{message}</div>}
    {adding && <form className="panel review-create" onSubmit={create}><div className="panel-header"><h2>新建复习卡片</h2></div><div className="panel-body review-create-fields"><label className="field-label">类型<select className="field" value={cardType} onChange={(event) => setCardType(event.target.value as CardType)}><option value="concept">知识点</option><option value="question">问答</option><option value="rule">公式与规则</option><option value="pitfall">易错点</option></select></label><label className="field-label">标题<input className="field" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required /></label><label className="field-label">内容<textarea className="field" value={body} onChange={(event) => setBody(event.target.value)} rows={4} maxLength={10000} required /></label><div><button className="button button-primary" disabled={busy}>保存卡片</button></div></div></form>}
    <section className="panel"><div className="panel-header"><h2>本节卡片</h2><span>{cards.length} 张</span></div><div className="panel-body">{cards.length ? <div className="review-card-grid">{cards.map((card) => <ReviewCardItem key={card.id} card={card} onReview={review} onSave={save} onDelete={remove} />)}</div> : <div className="empty-state"><strong>还没有复习卡片</strong><p>可以从智能纪要提取有原文依据的核心概念，也可以手动创建。</p></div>}</div></section>
  </main>;
}
