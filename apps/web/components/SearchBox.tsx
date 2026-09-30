"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

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

export default function SearchBox() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setResults(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      request<SearchResults>(`/search?q=${encodeURIComponent(term)}`, { signal: controller.signal })
        .then(setResults)
        .catch(() => {})
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function onMouseDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  const term = query.trim();
  const total = results
    ? results.courses.length + results.lessons.length + results.transcript.length + results.summaries.length
    : 0;
  const showDropdown = open && term.length > 0;

  return (
    <div className="search" ref={containerRef}>
      <input
        className="search-input"
        type="search"
        value={query}
        placeholder="搜索课程、课次、文字或纪要…"
        aria-label="站内搜索"
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "Enter") {
            const term = query.trim();
            if (term) {
              setOpen(false);
              router.push(`/search?q=${encodeURIComponent(term)}`);
            }
          }
        }}
      />
      {showDropdown && (
        <div className="search-dropdown" role="listbox">
          {loading && !results && <div className="search-empty">搜索中…</div>}
          {!loading && results && total === 0 && <div className="search-empty">没有找到与“{term}”相关的内容</div>}
          {results && results.courses.length > 0 && (
            <>
              <div className="search-section-label">课程</div>
              {results.courses.map((course) => (
                <Link key={course.id} className="search-item" href={`/courses/${course.id}`} onClick={() => setOpen(false)}>
                  <div className="search-item-title"><Highlight text={course.name} query={term} /></div>
                  <div className="search-item-sub">{course.semester || "未设置学期"}</div>
                </Link>
              ))}
            </>
          )}
          {results && results.lessons.length > 0 && (
            <>
              <div className="search-section-label">课次</div>
              {results.lessons.map((lesson) => (
                <Link key={lesson.id} className="search-item" href={`/lessons/${lesson.id}`} onClick={() => setOpen(false)}>
                  <div className="search-item-title"><Highlight text={lesson.title} query={term} /></div>
                  <div className="search-item-sub">课次 · {lesson.lesson_date || "未设置日期"}</div>
                </Link>
              ))}
            </>
          )}
          {results && results.transcript.length > 0 && (
            <>
              <div className="search-section-label">文字记录片段</div>
              {results.transcript.map((segment) => (
                <Link key={segment.segment_id} className="search-item" href={`/lessons/${segment.lesson_id}/transcript`} onClick={() => setOpen(false)}>
                  <div className="search-item-title"><Highlight text={segment.lesson_title} query={term} /><span className="search-count">{segment.course_name}</span></div>
                  <div className="search-item-snippet"><Highlight text={segment.snippet} query={term} /></div>
                </Link>
              ))}
            </>
          )}
          {results && results.summaries.length > 0 && (
            <>
              <div className="search-section-label">智能纪要命中</div>
              {results.summaries.map((summary) => (
                <Link key={summary.lesson_id} className="search-item" href={`/lessons/${summary.lesson_id}/summary`} onClick={() => setOpen(false)}>
                  <div className="search-item-title"><Highlight text={summary.lesson_title} query={term} /><span className="search-count">{summary.course_name}</span></div>
                  <div className="search-item-sub">该课次的智能纪要中包含“{term}”</div>
                </Link>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
