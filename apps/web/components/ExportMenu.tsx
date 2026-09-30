"use client";

import { useEffect, useRef, useState } from "react";
import type { SummaryContent } from "../app/lessons/[lessonId]/lesson-view";
import { buildLessonHtml, buildLessonMarkdown, buildLessonText, downloadText, printLesson } from "../lib/export";

type SegmentLike = { speaker: string; start_ms: number; end_ms: number; text: string };
type LessonLike = { title: string; lesson_date?: string | null };
type SpeakerLike = { raw_label: string; display_name: string };

export default function ExportMenu({ lesson, summary, segments, speakers }: { lesson: LessonLike; summary: SummaryContent | null; segments: SegmentLike[]; speakers?: SpeakerLike[] }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const speakerAliases = Object.fromEntries((speakers ?? []).map((item) => [item.raw_label, item.display_name]));

  useEffect(() => {
    if (!open) return;
    function onMouseDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  function exportMarkdown() {
    downloadText(`${lesson.title}-课堂资料.md`, buildLessonMarkdown({ lesson, summary, segments, speakerAliases }), "text/markdown");
    setOpen(false);
  }
  function exportText() {
    downloadText(`${lesson.title}-课堂资料.txt`, buildLessonText({ lesson, summary, segments, speakerAliases }), "text/plain");
    setOpen(false);
  }
  function exportPdf() {
    printLesson(`${lesson.title}-课堂资料`, buildLessonHtml({ lesson, summary, segments, speakerAliases }));
    setOpen(false);
  }

  return (
    <div className="export-menu" ref={containerRef}>
      <button className="button button-secondary" type="button" onClick={() => setOpen((value) => !value)} aria-haspopup="true" aria-expanded={open}>
        导出资料 ▾
      </button>
      {open && (
        <div className="export-list" role="menu">
          <button type="button" role="menuitem" className="export-item" onClick={exportMarkdown}>导出 Markdown</button>
          <button type="button" role="menuitem" className="export-item" onClick={exportText}>导出 TXT 文本</button>
          <button type="button" role="menuitem" className="export-item" onClick={exportPdf}>打印 / 导出 PDF</button>
        </div>
      )}
    </div>
  );
}
