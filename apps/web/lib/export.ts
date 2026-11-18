import DOMPurify from "dompurify";
import { summaryToHtml } from "./summary-html";
import { lessonPrintStyles } from "./export-styles";
import type { SummaryContent } from "../app/lessons/[lessonId]/lesson-view";

type SegmentLike = { speaker: string; start_ms: number; end_ms: number; text: string };
type LessonLike = { title: string; lesson_date?: string | null };

function formatTime(ms: number) {
  const seconds = Math.floor(Math.max(0, ms) / 1000);
  const minutes = Math.floor(seconds / 60);
  const tail = `${String(minutes % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return minutes >= 60 ? `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${tail}` : tail;
}

export function summaryToMarkdown(content: SummaryContent): string {
  content = JSON.parse(JSON.stringify(content, (_key, value) => typeof value === "string" ? escapeMarkdown(value) : value)) as SummaryContent;
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

export type ExportOptions = { lesson: LessonLike; summary: SummaryContent | null; summaryHtml?: string | null; segments: SegmentLike[]; speakerAliases?: Record<string, string> };

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!));
const escapeMarkdown = (value: string) => value.replace(/([\\`*_{}[\]()<>#+.!|~-])/g, "\\$1");
const speakerName = (opts: ExportOptions, raw: string) => opts.speakerAliases?.[raw] || raw || "未标记说话人";
const timeRange = (segment: SegmentLike) => `${formatTime(segment.start_ms)} - ${formatTime(Math.max(segment.start_ms, segment.end_ms))}`;

function editedDocument(html: string): Document {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "h1", "h2", "h3", "blockquote", "hr", "code", "a", "span", "input"],
    ALLOWED_ATTR: ["href", "data-type", "data-checked", "type", "checked", "disabled", "start"],
  });
  const doc = new DOMParser().parseFromString(clean, "text/html");
  doc.querySelectorAll("input").forEach((input) => {
    if (input.getAttribute("type") !== "checkbox") input.remove();
    else input.setAttribute("disabled", "");
  });
  doc.querySelectorAll("h1,h2,h3").forEach((heading) => {
    const replacement = doc.createElement(`h${Number(heading.tagName.slice(1)) + 2}`);
    replacement.append(...Array.from(heading.childNodes));
    heading.replaceWith(replacement);
  });
  return doc;
}

function editedToText(html: string, markdown: boolean): string {
  const doc = editedDocument(html);
  function walk(node: Node): string {
    if (node.nodeType === 3) return markdown ? escapeMarkdown(node.textContent || "") : node.textContent || "";
    if (node.nodeType !== 1) return "";
    const element = node as Element;
    const content = () => Array.from(node.childNodes).map(walk).join("");
    const tag = element.tagName.toLowerCase();
    if (/^h[1-6]$/.test(tag)) return `\n\n${markdown ? "#".repeat(Number(tag[1])) + " " : "【"}${content().trim()}${markdown ? "" : "】"}\n\n`;
    if (tag === "p") return `${content()}\n\n`;
    if (tag === "br") return "\n";
    if (tag === "hr") return "\n\n---\n\n";
    if (tag === "input") return "";
    if (tag === "ul" || tag === "ol") {
      const start = Number(element.getAttribute("start")) || 1;
      return "\n" + Array.from(element.children).filter((child) => child.tagName === "LI").map((child, index) => {
        const task = element.getAttribute("data-type") === "taskList";
        const checked = child.getAttribute("data-checked") === "true" || !!child.querySelector("input[checked]");
        const prefix = task ? `- [${checked ? "x" : " "}] ` : tag === "ol" ? `${start + index}. ` : "- ";
        return prefix + walk(child).trim().replace(/\n[ \t]*\n/g, "\n").replace(/\n/g, "\n  ");
      }).join("\n") + "\n\n";
    }
    if (tag === "blockquote") return "\n" + content().trim().split("\n").map((line) => `${markdown ? "> " : "  "}${line}`).join("\n") + "\n\n";
    if (markdown && ["strong", "b"].includes(tag)) return `**${content()}**`;
    if (markdown && ["em", "i"].includes(tag)) return `*${content()}*`;
    if (markdown && tag === "code") return `\`${content()}\``;
    return content();
  }
  return Array.from(doc.body.childNodes).map(walk).join("").replace(/\n[ \t]+\n/g, "\n\n").replace(/\n{3,}/g, "\n\n").trim();
}

function metadata(opts: ExportOptions): string[] {
  const result = [opts.lesson.lesson_date ? `上课日期：${opts.lesson.lesson_date}` : ""];
  if (opts.segments.length) {
    const end = opts.segments.reduce((end, item) => Math.max(end, item.end_ms), 0);
    result.push(`记录至 ${formatTime(end)}`, `文字片段 ${opts.segments.length} 段`, `说话人 ${new Set(opts.segments.map((item) => speakerName(opts, item.speaker))).size} 位`);
  }
  return result.filter(Boolean);
}

export function buildLessonMarkdown(opts: ExportOptions): string {
  const summary = opts.summaryHtml ? editedToText(opts.summaryHtml, true) : opts.summary ? summaryToMarkdown(opts.summary) : "暂无智能纪要。";
  const transcript = opts.segments.map((segment, index) => `### ${String(index + 1).padStart(3, "0")} · ${escapeMarkdown(speakerName(opts, segment.speaker))}\n\n> ${timeRange(segment)}\n\n${escapeMarkdown(segment.text)}`).join("\n\n");
  return [`# ${escapeMarkdown(opts.lesson.title)}`, "> ClassAgent · 课堂学习资料", metadata(opts).join(" · "), "---", "## 智能纪要", summary, "---", "## 文字记录", transcript || "暂无文字记录。"].filter(Boolean).join("\n\n") + "\n";
}

export function buildTranscriptText(opts: ExportOptions): string {
  const transcript = opts.segments.map((segment, index) => `${String(index + 1).padStart(3, "0")}  ${timeRange(segment)}  |  ${speakerName(opts, segment.speaker)}\n${segment.text}`).join("\n\n");
  return [opts.lesson.title, "ClassAgent · 课堂文字记录", metadata(opts).join(" · "), "────────────────────────────", transcript || "暂无文字记录。"].filter(Boolean).join("\n\n") + "\n";
}

export function buildLessonText(opts: ExportOptions): string {
  const summary = opts.summaryHtml ? editedToText(opts.summaryHtml, false) : opts.summary ? summaryToText(opts.summary) : "暂无智能纪要。";
  const transcript = opts.segments.map((segment, index) => `${String(index + 1).padStart(3, "0")}  ${timeRange(segment)}  |  ${speakerName(opts, segment.speaker)}\n${segment.text}`).join("\n\n");
  return [opts.lesson.title, "ClassAgent · 课堂学习资料", metadata(opts).join(" · "), "════════════════════════════", "一、智能纪要", summary, "════════════════════════════", "二、文字记录", transcript || "暂无文字记录。"].filter(Boolean).join("\n\n") + "\n";
}

export function buildLessonHtml(opts: ExportOptions): string {
  const hasSummary = !!(opts.summaryHtml || opts.summary);
  const summary = opts.summaryHtml ? editedDocument(opts.summaryHtml).body.innerHTML : opts.summary ? summaryToHtml(opts.summary) : '<p class="empty">暂无智能纪要。</p>';
  const transcript = opts.segments.map((segment, index) => `<article class="transcript-item${segment.text.length > 1200 ? " long-segment" : ""}"><div class="segment-meta"><span class="segment-index">${String(index + 1).padStart(3, "0")}</span><span>${timeRange(segment)}</span><strong>${escapeHtml(speakerName(opts, segment.speaker))}</strong></div><p>${escapeHtml(segment.text)}</p></article>`).join("") || '<p class="empty">暂无文字记录。</p>';
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>${escapeHtml(opts.lesson.title)} · 课堂资料</title><style>${lessonPrintStyles}</style></head><body><main class="report"><header class="report-header"><div class="eyebrow"><span class="brand">ClassAgent</span><span>课堂学习资料</span></div><h1>${escapeHtml(opts.lesson.title)}</h1><div class="metadata">${metadata(opts).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></header><section class="summary"><div class="section-heading"><span>01</span><h2>智能纪要</h2><small>梳理课堂重点</small></div><div class="summary-body">${summary}</div></section><section class="transcript${hasSummary && opts.segments.length ? " new-page" : ""}"><div class="section-heading"><span>02</span><h2>文字记录</h2><small>${opts.segments.length} 段 · 按时间顺序</small></div>${transcript}</section><footer class="report-footer">ClassAgent · 记录、理解与复习</footer></main></body></html>`;
}

export function exportFilename(title: string, suffix = "课堂资料"): string {
  const safe = title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").trim().slice(0, 100);
  return `${safe || "课堂"}-${suffix}`;
}

export function downloadText(filename: string, content: string, mime: string) {
  const text = mime === "text/plain" ? "\uFEFF" + content.replace(/\r?\n/g, "\r\n") : content;
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function printLesson(filename: string, html: string) {
  const win = window.open("", "_blank");
  if (!win) {
    alert("浏览器拦截了打印窗口，请允许弹出窗口后重试。");
    return;
  }
  win.opener = null;
  win.document.open();
  win.document.write(html);
  win.document.title = filename;
  win.document.close();
  void win.document.fonts.ready.then(() => {
    win.requestAnimationFrame(() => win.requestAnimationFrame(() => {
      if (!win.closed) { win.focus(); win.print(); }
    }));
  });
}
