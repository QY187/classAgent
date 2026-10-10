"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { errorMessage, request } from "../../lib/api";
import { quizSourceUrl, type WrongQuestion, type WrongQuestionResult } from "../../lib/quizzes";
import WrongQuestionPractice from "../../components/WrongQuestionPractice";

type Course = { id: string; name: string };
type Status = "all" | WrongQuestion["status"];

function WrongQuestionBook() {
  const params = useSearchParams();
  const [items, setItems] = useState<WrongQuestion[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState(params.get("course") || "");
  const [courseQuery, setCourseQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [status, setStatus] = useState<Status>("pending");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selection, setSelection] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<WrongQuestionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [retryError, setRetryError] = useState("");
  const [limit, setLimit] = useState(20);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectionOnly, setSelectionOnly] = useState(false);
  const [practiceQuestions, setPracticeQuestions] = useState<WrongQuestion[] | null>(null);

  useEffect(() => {
    setCourseId(params.get("course") || "");
    setCourseQuery(""); setActiveId(null); setOutcome(null); setSelection(null); setRetryError(""); setLimit(20);
    setSelectedIds([]); setSelectionOnly(false);
    setPracticeQuestions(null);
  }, [params]);

  useEffect(() => {
    setSelectedIds([]); setSelectionOnly(false);
  }, [courseId, courseQuery, status]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([request<WrongQuestion[]>("/wrong-questions", { signal: controller.signal }), request<Course[]>("/courses", { signal: controller.signal })])
      .then(([wrongs, available]) => { setItems(wrongs); setCourses(available); })
      .catch((err) => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  const selectedCourse = courses.find((course) => course.id === courseId);
  const matchingCourses = courses.filter((course) => course.name.toLocaleLowerCase().includes(courseQuery.trim().toLocaleLowerCase()));
  const scoped = items.filter((item) => courseId ? item.course_id === courseId : item.course_name.toLocaleLowerCase().includes(courseQuery.trim().toLocaleLowerCase()));
  const pendingCount = scoped.filter((item) => item.status === "pending").length;
  // Keep the submitted question visible until the user closes it, even if its status changes.
  const filtered = scoped.filter((item) => status === "all" || item.status === status || item.id === activeId);
  const visible = filtered.filter((item) => !selectionOnly || selectedIds.includes(item.id));

  function clearSelection() {
    setSelectedIds([]); setSelectionOnly(false);
  }

  function toggleSelection(id: string) {
    if (selectedIds.length === 1 && selectedIds[0] === id) setSelectionOnly(false);
    setSelectedIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  function closePractice() {
    setActiveId(null); setSelection(null); setOutcome(null); setRetryError("");
  }

  function startPractice(item: WrongQuestion) {
    setActiveId(item.id); setSelection(null); setOutcome(null); setRetryError("");
  }

  function applyResult(questionId: string, result: WrongQuestionResult) {
    setItems((current) => current.map((question) => question.id === questionId ? {
      ...question, status: result.is_correct ? "mastered" : "pending", retry_count: question.retry_count + 1, last_retry_at: result.created_at,
    } : question));
  }

  function startRound() {
    const questions = scoped.filter((item) => selectedIds.includes(item.id));
    if (!questions.length) return;
    closePractice(); setMenuOpen(false); setPracticeQuestions(questions);
  }

  async function submit(item: WrongQuestion) {
    if (selection === null || busy) return;
    setBusy(true); setMenuOpen(false); setRetryError("");
    try {
      const result = await request<WrongQuestionResult>(`/wrong-questions/${item.id}/retries`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected_option: selection }),
      });
      setOutcome(result);
      applyResult(item.id, result);
    } catch (err) { setRetryError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  return <main className="content wrong-book-page">
    <section className="page-hero page-hero-compact"><span className="page-hero-icon">▤</span><div className="page-hero-copy"><div className="eyebrow">课堂小测 · 课后巩固</div><h1>错题本</h1><p>答错的题自动收录，重新练习后查看解析和课堂依据。</p></div><div className="page-hero-actions"><Link className="button button-secondary" href="/">返回课程库</Link></div></section>
    {error && <p className="notice" role="alert">{error}</p>}
    {practiceQuestions ? <WrongQuestionPractice questions={practiceQuestions} onResult={applyResult} onClose={() => { setPracticeQuestions(null); clearSelection(); }} /> : <section className="panel">
      <div className="panel-header"><h2>我的错题</h2><span>{loading ? "加载中" : `${scoped.length} 道错题 · ${pendingCount} 道待巩固`}</span></div>
      <div className="panel-body">
        <div className="review-course-filter">
          <div className="review-filter-course" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setMenuOpen(false); }}>
            <label htmlFor="wrong-course-search">筛选课程</label>
            <input id="wrong-course-search" className="field" role="combobox" aria-expanded={menuOpen} aria-controls="wrong-course-menu" aria-autocomplete="list" placeholder="全部课程 · 点击选择或搜索" disabled={busy} value={selectedCourse?.name ?? courseQuery} onFocus={(event) => { setMenuOpen(true); if (courseId) event.currentTarget.select(); }} onChange={(event) => { closePractice(); setCourseId(""); setCourseQuery(event.target.value); setMenuOpen(true); setLimit(20); }} onKeyDown={(event) => { if (event.key === "Escape") setMenuOpen(false); }} />
            {menuOpen && <div className="review-course-menu" id="wrong-course-menu" role="listbox" aria-label="课程列表">
              <button type="button" role="option" aria-selected={!courseId && !courseQuery} onClick={() => { closePractice(); setCourseId(""); setCourseQuery(""); setMenuOpen(false); setLimit(20); }}>全部课程</button>
              {matchingCourses.map((course) => <button type="button" role="option" aria-selected={courseId === course.id} key={course.id} onClick={() => { closePractice(); setCourseId(course.id); setCourseQuery(""); setMenuOpen(false); setLimit(20); }}>{course.name}</button>)}
              {!matchingCourses.length && <p>没有匹配的课程</p>}
            </div>}
          </div>
          <div className="review-filter-status"><span className="review-filter-label">巩固状态</span><div className="review-status-filter" role="group" aria-label="巩固状态">{(["pending", "mastered", "all"] as Status[]).map((value) => <button type="button" key={value} disabled={busy} className={status === value ? "active" : ""} aria-pressed={status === value} onClick={() => { closePractice(); setStatus(value); setLimit(20); }}>{value === "pending" ? `待巩固 ${pendingCount}` : value === "mastered" ? `已巩固 ${scoped.length - pendingCount}` : `全部 ${scoped.length}`}</button>)}</div></div>
        </div>
        {!loading && !error && scoped.length > 0 && <div className="wrong-book-selection" role="group" aria-label="选择重练错题">
          <span>已选 <strong>{selectedIds.length}</strong> 道</span>
          <button type="button" className="button button-primary" disabled={busy || !selectedIds.length} onClick={startRound}>开始重练{selectedIds.length > 0 && `（${selectedIds.length} 道）`}</button>
          <button type="button" className="button button-secondary" disabled={busy || !filtered.length} onClick={() => setSelectedIds(filtered.map((item) => item.id))}>选中当前筛选结果</button>
          <label><input type="checkbox" checked={selectionOnly} disabled={busy || !selectedIds.length} onChange={(event) => { setSelectionOnly(event.target.checked); setLimit(20); }} />仅看已选</label>
          <button type="button" className="button button-quiet" disabled={busy || !selectedIds.length} onClick={clearSelection}>清空选择</button>
        </div>}
        {loading ? <p role="status">正在整理错题…</p> : error ? <div className="empty-state"><strong>错题加载失败</strong><button className="button button-secondary" onClick={() => window.location.reload()}>重新加载</button></div> : visible.length ? <div className="wrong-book-list">{visible.slice(0, limit).map((item) => {
          const expanded = activeId === item.id;
          return <article className={`wrong-book-item${expanded ? " is-open" : ""}`} key={item.id}>
            <div className="wrong-book-item-head"><label className="wrong-book-select"><input type="checkbox" disabled={busy} checked={selectedIds.includes(item.id)} onChange={() => toggleSelection(item.id)} aria-label={`选择错题：${item.stem}`} />选择</label><span className={`wrong-book-status ${item.status}`}>{item.status === "pending" ? "待巩固" : "已巩固"}</span><span>{item.kind === "true_false" ? "判断题" : "单选题"} · 小测答错 {item.wrong_count} 次{item.retry_count > 0 && ` · 已重做 ${item.retry_count} 次`}</span></div>
            <h3>{item.stem}</h3>
            <div className="wrong-book-meta"><Link href={`/courses/${item.course_id}`}>{item.course_name}</Link><span>{item.quiz_title}</span><span>最近答错：{new Date(item.last_wrong_at).toLocaleDateString("zh-CN")}</span></div>
            <div className="wrong-book-actions"><button className="button button-primary" disabled={busy} onClick={() => expanded ? closePractice() : startPractice(item)} aria-expanded={expanded} aria-controls={`practice-${item.id}`}>{expanded ? "收起练习" : "重新练习"}</button><Link className="button button-secondary" href={`/quiz-attempts/${item.last_attempt_id}#question-${item.id}`}>查看原答题记录</Link></div>
            {expanded && <div className="wrong-book-practice" id={`practice-${item.id}`}>
              <fieldset disabled={busy || !!outcome} className="wrong-book-choices"><legend>重新选择答案</legend>{item.options.map((option, index) => <label className={`wrong-book-choice${selection === index ? " is-selected" : ""}${outcome && index === outcome.correct_option ? " is-answer" : ""}${outcome && !outcome.is_correct && index === outcome.selected_option ? " is-wrong" : ""}`} key={index}><input type="radio" name={`retry-${item.id}`} value={index} checked={selection === index} onChange={() => setSelection(index)} /><span>{String.fromCharCode(65 + index)}. {option}</span>{outcome && index === outcome.correct_option && <b>正确答案</b>}</label>)}</fieldset>
              {retryError && <p className="notice" role="alert">{retryError}</p>}
              {outcome ? <div className="wrong-book-feedback" role="status"><strong>{outcome.is_correct ? "回答正确，已归入已巩固" : "本次答错，继续保留在待巩固"}</strong><div className="quiz-result-explanation"><strong>解析</strong><p>{outcome.explanation}</p></div><div className="quiz-evidence"><strong>课堂依据</strong><p>{outcome.source_excerpt}</p>{quizSourceUrl(outcome) && <Link href={quizSourceUrl(outcome)!}>回到文字记录 ↗</Link>}</div><button className="button button-secondary" onClick={() => startPractice(item)}>再练一次</button></div> : <button className="button button-primary" disabled={selection === null || busy} onClick={() => submit(item)}>{busy ? "正在判分…" : "提交答案"}</button>}
            </div>}
          </article>;
        })}{visible.length > limit && <button className="button button-secondary" onClick={() => setLimit((current) => current + 20)}>查看更多错题</button>}</div> : <div className="empty-state"><strong>{items.length === 0 ? "还没有错题" : status === "pending" && scoped.length ? "这门课程的错题已全部巩固" : "没有符合条件的错题"}</strong><p>{items.length === 0 ? "完成课堂小测后，答错的题会自动出现在这里。" : "可以切换课程或巩固状态查看。"}</p></div>}
      </div>
    </section>}
  </main>;
}

export default function Page() {
  return <Suspense fallback={<main className="content"><p role="status">正在加载错题本…</p></main>}><WrongQuestionBook /></Suspense>;
}
