import type { SummaryContent } from "../app/lessons/[lessonId]/lesson-view";

type SegmentLike = { speaker: string; start_ms: number; end_ms: number; text: string };
type LessonLike = { title: string; lesson_date?: string | null };

function formatTime(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function summaryToMarkdown(content: SummaryContent): string {
  const lines: string[] = [];
  const pushList = (title: string, items: string[] | undefined) => {
    if (items && items.length) {
      lines.push(`### ${title}`);
      items.forEach((item) => lines.push(`- ${item}`));
      lines.push("");
    }
  };

  if (content.overview) {
    lines.push(`**概览**：${content.overview}`, "");
  }
  pushList("学习目标", content.learning_goals);

  if (content.chapter_flow?.length) {
    lines.push("### 章节脉络");
    content.chapter_flow.forEach((item, index) => {
      lines.push(`${index + 1}. **${item.title}**${item.time_range ? ` （${item.time_range}）` : ""}`);
      if (item.summary) lines.push(`   ${item.summary}`);
    });
    lines.push("");
  }

  if (content.topics?.length) {
    lines.push("### 主题与重点");
    content.topics.forEach((topic) => {
      lines.push(`- **${topic.title}**${topic.time_range ? ` （${topic.time_range}）` : ""}`);
      if (topic.summary) lines.push(`  - ${topic.summary}`);
      topic.points?.forEach((point) => lines.push(`  - ${point}`));
      if (topic.takeaway) lines.push(`  - 记住：${topic.takeaway}`);
    });
    lines.push("");
  }

  if (content.key_concepts?.length) {
    lines.push("### 核心概念");
    content.key_concepts.forEach((concept) => {
      lines.push(`- **${concept.term}**：${concept.definition}`);
      if (concept.importance) lines.push(`  - 重要性：${concept.importance}`);
    });
    lines.push("");
  }

  pushList("关键结论", content.key_takeaways);
  pushList("老师强调", content.teacher_emphasis);

  if (content.examples?.length) {
    lines.push("### 例题与案例");
    content.examples.forEach((example) => {
      lines.push(`- **${example.title}**`);
      if (example.context) lines.push(`  - 背景：${example.context}`);
      if (example.explanation) lines.push(`  - 思路：${example.explanation}`);
      if (example.conclusion) lines.push(`  - 结论：${example.conclusion}`);
    });
    lines.push("");
  }

  if (content.assignments?.length || content.questions?.length) {
    pushList("作业与后续安排", content.assignments);
    pushList("课堂问题", content.questions);
  }
  if (content.review_questions?.length || content.to_verify?.length) {
    if (content.review_questions?.length) {
      lines.push("### 复习自测");
      content.review_questions.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
      lines.push("");
    }
    pushList("待核对内容", content.to_verify);
  }

  if (content.keywords?.length) {
    lines.push(`**关键词**：${content.keywords.join("、")}`, "");
  }

  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function summaryToText(content: SummaryContent): string {
  const lines: string[] = [];
  const pushList = (title: string, items: string[] | undefined) => {
    if (items && items.length) {
      lines.push(title);
      items.forEach((item) => lines.push(`- ${item}`));
      lines.push("");
    }
  };
  if (content.overview) {
    lines.push("概览：", content.overview, "");
  }
  pushList("学习目标", content.learning_goals);
  if (content.chapter_flow?.length) {
    lines.push("章节脉络");
    content.chapter_flow.forEach((item, index) => {
      lines.push(`${index + 1}. ${item.title}${item.time_range ? ` （${item.time_range}）` : ""}`);
      if (item.summary) lines.push(`   ${item.summary}`);
    });
    lines.push("");
  }
  if (content.topics?.length) {
    lines.push("主题与重点");
    content.topics.forEach((topic) => {
      lines.push(`- ${topic.title}${topic.time_range ? ` （${topic.time_range}）` : ""}`);
      if (topic.summary) lines.push(`   ${topic.summary}`);
      topic.points?.forEach((point) => lines.push(`   - ${point}`));
      if (topic.takeaway) lines.push(`   记住：${topic.takeaway}`);
    });
    lines.push("");
  }
  if (content.key_concepts?.length) {
    lines.push("核心概念");
    content.key_concepts.forEach((concept) => {
      lines.push(`- ${concept.term}：${concept.definition}`);
      if (concept.importance) lines.push(`  重要性：${concept.importance}`);
    });
    lines.push("");
  }
  pushList("关键结论", content.key_takeaways);
  pushList("老师强调", content.teacher_emphasis);
  if (content.examples?.length) {
    lines.push("例题与案例");
    content.examples.forEach((example) => {
      lines.push(`- ${example.title}`);
      if (example.context) lines.push(`  背景：${example.context}`);
      if (example.explanation) lines.push(`  思路：${example.explanation}`);
      if (example.conclusion) lines.push(`  结论：${example.conclusion}`);
    });
    lines.push("");
  }
  pushList("作业与后续安排", content.assignments);
  pushList("课堂问题", content.questions);
  if (content.review_questions?.length) {
    lines.push("复习自测");
    content.review_questions.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
    lines.push("");
  }
  pushList("待核对内容", content.to_verify);
  if (content.keywords?.length) lines.push(`关键词：${content.keywords.join("、")}`, "");
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function buildLessonMarkdown(opts: { lesson: LessonLike; summary: SummaryContent | null; segments: SegmentLike[] }): string {
  const { lesson, summary, segments } = opts;
  const head = [`# ${lesson.title}`, lesson.lesson_date ? `> ${lesson.lesson_date}` : "", ""];
  const summaryBlock = summary ? ["## 智能纪要", "", summaryToMarkdown(summary), ""] : ["## 智能纪要", "", "_暂无智能纪要_", ""];
  const transcriptLines = segments.length
    ? segments.map((segment) => `[${formatTime(segment.start_ms)}] ${segment.speaker}\n${segment.text}`)
    : ["_暂无文字记录_"];
  const transcriptBlock = ["## 文字记录", "", ...transcriptLines];
  return [...head, ...summaryBlock, ...transcriptBlock].join("\n").trim() + "\n";
}

export function buildLessonText(opts: { lesson: LessonLike; summary: SummaryContent | null; segments: SegmentLike[] }): string {
  const { lesson, summary, segments } = opts;
  const head = [`${lesson.title}`, lesson.lesson_date ? lesson.lesson_date : "", "====================", ""];
  const summaryBlock = summary ? ["【智能纪要】", summaryToText(summary), ""] : ["【智能纪要】", "（暂无）", ""];
  const transcriptLines = segments.length
    ? segments.map((segment) => `[${formatTime(segment.start_ms)}] ${segment.speaker}\n${segment.text}`)
    : ["（暂无文字记录）"];
  const transcriptBlock = ["【文字记录】", ...transcriptLines];
  return [...head, ...summaryBlock, ...transcriptBlock].join("\n").trim() + "\n";
}

export function buildLessonHtml(opts: { lesson: LessonLike; summary: SummaryContent | null; segments: SegmentLike[] }): string {
  const { lesson, summary, segments } = opts;
  const escape = (value: string) => value.replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char] as string));
  const md = buildLessonMarkdown({ lesson, summary, segments });
  const body = escape(md).replace(/\n/g, "<br/>");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${escape(lesson.title)}</title></head><body style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#1f2937;line-height:1.8">${body}</body></html>`;
}

export function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function printLesson(filename: string, html: string) {
  const win = window.open("", "_blank");
  if (!win) {
    alert("浏览器拦截了打印窗口，请允许弹出窗口后重试。");
    return;
  }
  win.document.open();
  win.document.write(html);
  win.document.title = filename;
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 300);
}
