"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { errorMessage, request } from "../../lib/api";

type SearchResults = {
  query: string;
  courses: { id: string; name: string; semester?: string | null }[];
  lessons: { id: string; course_id: string; title: string; lesson_date?: string | null }[];
  transcript: { segment_id: string; lesson_id: string; course_id: string; lesson_title: string; course_name: string; speaker: string; start_ms: number; text: string; snippet: string }[];
  summaries: { lesson_id: string; course_id: string; lesson_title: string; course_name: string }[];
};

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "ig"));
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === query.toLowerCase() ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>,
      )}
    </>
  );
}

function formatTime(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function SearchResultsPage() {
  const params = useSearchParams();
  const query = params.get("q")?.trim() ?? "";
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!query) {
      setResults(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    request<SearchResults>(`/search?q=${encodeURIComponent(query)}`, { signal: controller.signal })
      .then(setResults)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query]);

  const total = results
    ? results.courses.length + results.lessons.length + results.transcript.length + results.summaries.length
    : 0;

  return (
    <div className="page page-search">
      <div className="page-hero">
        <div className="eyebrow">站内检索</div>
        <h1>搜索结果</h1>
        <p>{query ? <>关键词：<strong>{query}</strong></> : "请输入关键词进行检索"}</p>
      </div>

      {error && <div className="notice">{error}</div>}

      {!query && (
        <div className="empty-state">
          <div className="empty-icon">⌕</div>
          <strong>还没有检索词</strong>
          <p>在右上角搜索框输入课程、课次、文字记录或纪要关键词后回车即可。</p>
        </div>
      )}

      {query && loading && !results && <div className="empty-state"><div className="empty-icon">⌕</div><strong>检索中…</strong></div>}

      {results && total === 0 && (
        <div className="empty-state">
          <div className="empty-icon">⌕</div>
          <strong>没有找到相关内容</strong>
          <p>换个关键词试试，或检查是否在别的课程中。</p>
        </div>
      )}

      {results && total > 0 && (
        <div className="search-results">
          <section className="panel">
            <div className="panel-header"><div><h2>课程</h2><span className="summary-caption">{results.courses.length} 个匹配</span></div></div>
            <div className="panel-body">
              {results.courses.map((course) => (
                <Link key={course.id} className="result-row" href={`/courses/${course.id}`}>
                  <div className="result-title"><Highlight text={course.name} query={query} /></div>
                  <div className="result-sub">{course.semester || "未设置学期"}</div>
                </Link>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><div><h2>课次</h2><span className="summary-caption">{results.lessons.length} 个匹配</span></div></div>
            <div className="panel-body">
              {results.lessons.map((lesson) => (
                <Link key={lesson.id} className="result-row" href={`/lessons/${lesson.id}`}>
                  <div className="result-title"><Highlight text={lesson.title} query={query} /></div>
                  <div className="result-sub">课次 · {lesson.lesson_date || "未设置日期"}</div>
                </Link>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><div><h2>文字记录片段</h2><span className="summary-caption">{results.transcript.length} 处命中</span></div></div>
            <div className="panel-body">
              {results.transcript.map((segment) => (
                <Link key={segment.segment_id} className="result-row" href={`/lessons/${segment.lesson_id}/transcript?t=${segment.start_ms}`}>
                  <div className="result-meta">{segment.course_name} · {segment.lesson_title} · {segment.speaker} · {formatTime(segment.start_ms)}</div>
                  <div className="result-title"><Highlight text={segment.snippet} query={query} /></div>
                </Link>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header"><div><h2>智能纪要命中</h2><span className="summary-caption">{results.summaries.length} 个课次</span></div></div>
            <div className="panel-body">
              {results.summaries.map((summary) => (
                <Link key={summary.lesson_id} className="result-row" href={`/lessons/${summary.lesson_id}/summary`}>
                  <div className="result-title"><Highlight text={summary.lesson_title} query={query} /></div>
                  <div className="result-sub">{summary.course_name} 的智能纪要中包含“{query}”</div>
                </Link>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  return <Suspense fallback={<div className="page page-search"><p role="status">正在加载搜索…</p></div>}><SearchResultsPage /></Suspense>;
}
