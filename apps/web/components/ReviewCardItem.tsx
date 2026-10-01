"use client";

import Link from "next/link";
import { useState } from "react";
import { cardStatusLabel, cardTypeLabel, reviewTime, type CardStatus, type CardType, type ReviewCard } from "../lib/review-cards";

type Props = {
  card: ReviewCard;
  onReview: (card: ReviewCard, status: CardStatus) => Promise<void>;
  onSave?: (card: ReviewCard, changes: { title: string; body: string; card_type: CardType }) => Promise<void>;
  onDelete?: (card: ReviewCard) => Promise<void>;
};

export default function ReviewCardItem({ card, onReview, onSave, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [title, setTitle] = useState(card.title);
  const [body, setBody] = useState(card.body);
  const [cardType, setCardType] = useState<CardType>(card.card_type);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请重试"); }
    finally { setBusy(false); }
  }

  return <article className="review-card">
    <div className="review-card-top"><span className="review-card-kind">{cardTypeLabel[card.card_type]}</span><span className={`review-card-status review-card-status-${card.status}`}>{cardStatusLabel[card.status]}</span></div>
    {editing ? <form className="review-card-edit" onSubmit={(event) => {
      event.preventDefault();
      if (!title.trim() || !body.trim() || !onSave) return;
      run(async () => { await onSave(card, { title: title.trim(), body: body.trim(), card_type: cardType }); setEditing(false); });
    }}>
      <select className="field" value={cardType} onChange={(event) => setCardType(event.target.value as CardType)} aria-label="卡片类型"><option value="concept">知识点</option><option value="question">问答</option><option value="rule">公式与规则</option><option value="pitfall">易错点</option></select>
      <input className="field" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} aria-label="卡片标题" required />
      <textarea className="field" value={body} onChange={(event) => setBody(event.target.value)} rows={4} maxLength={10000} aria-label="卡片内容" required />
      <div className="review-card-actions"><button className="button button-primary" disabled={busy} type="submit">保存</button><button className="button button-secondary" type="button" onClick={() => setEditing(false)} disabled={busy}>取消</button></div>
    </form> : <><h3>{card.title}</h3><p className="review-card-body">{card.body}</p></>}
    {card.source_start_ms !== null && <div className="review-card-source"><Link href={`/lessons/${card.lesson_id}/transcript?t=${card.source_start_ms}`}>查看原文 · {card.lesson_title} {reviewTime(card.source_start_ms)} ↗</Link>{card.source_excerpt && <span>{card.source_excerpt}</span>}</div>}
    <div className="review-card-footer"><span>下次复习：{new Date(card.next_review_at).toLocaleDateString("zh-CN")}</span><div className="review-card-actions">
      {!editing && onSave && <button type="button" className="review-card-link" onClick={() => { setTitle(card.title); setBody(card.body); setCardType(card.card_type); setEditing(true); }}>编辑</button>}
      {!editing && onDelete && <button type="button" className="review-card-link danger" onClick={() => setConfirmDelete(true)}>删除</button>}
    </div></div>
    {confirmDelete && <div className="review-card-confirm"><span>确定删除这张卡片？</span><button className="button button-secondary" type="button" onClick={() => setConfirmDelete(false)} disabled={busy}>取消</button><button className="button button-primary" type="button" onClick={() => run(async () => { await onDelete?.(card); setConfirmDelete(false); })} disabled={busy}>删除</button></div>}
    <div className="review-card-review"><span>这次复习后：</span>{(["new", "review", "mastered"] as CardStatus[]).map((status) => <button type="button" key={status} className={`review-choice ${card.status === status ? "active" : ""}`} disabled={busy} onClick={() => run(() => onReview(card, status))}>{cardStatusLabel[status]}</button>)}</div>
    {error && <p className="review-card-error" role="alert">{error}</p>}
  </article>;
}
