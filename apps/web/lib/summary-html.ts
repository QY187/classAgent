import type { SummaryContent } from "../app/lessons/[lessonId]/lesson-view";

const escapeHtml = (value: string) => value.replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char] as string));
const paragraph = (value?: string) => value ? `<p>${escapeHtml(value)}</p>` : "";
const list = (items?: string[], ordered = false) => items?.length
  ? `<${ordered ? "ol" : "ul"}>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`
  : "";
const section = (title: string, body: string) => body ? `<h3>${title}</h3>${body}` : "";
const label = (title: string, timeRange?: string) => `<strong>${escapeHtml(title)}</strong>${timeRange ? ` （${escapeHtml(timeRange)}）` : ""}`;

export function summaryToHtml(content: SummaryContent): string {
  const parts: string[] = [];
  if (content.overview) parts.push(`<p><strong>概览</strong>：${escapeHtml(content.overview)}</p>`);
  parts.push(section("学习目标", list(content.learning_goals)));

  parts.push(section("章节脉络", content.chapter_flow?.length
    ? `<ol>${content.chapter_flow.map((item) => `<li>${label(item.title, item.time_range)}${paragraph(item.summary)}</li>`).join("")}</ol>`
    : ""));

  parts.push(section("主题与重点", content.topics?.length
    ? `<ul>${content.topics.map((topic) => `<li>${label(topic.title, topic.time_range)}${paragraph(topic.summary)}${list(topic.points)}${topic.takeaway ? `<p><strong>记住：</strong>${escapeHtml(topic.takeaway)}</p>` : ""}</li>`).join("")}</ul>`
    : ""));

  parts.push(section("核心概念", content.key_concepts?.length
    ? `<ul>${content.key_concepts.map((concept) => `<li><strong>${escapeHtml(concept.term)}</strong>：${escapeHtml(concept.definition)}${concept.importance ? `<p><strong>重要性：</strong>${escapeHtml(concept.importance)}</p>` : ""}</li>`).join("")}</ul>`
    : ""));

  parts.push(section("关键结论", list(content.key_takeaways)));
  parts.push(section("老师强调", list(content.teacher_emphasis)));

  parts.push(section("例题与案例", content.examples?.length
    ? `<ul>${content.examples.map((example) => `<li><strong>${escapeHtml(example.title)}</strong>${example.context ? `<p><strong>背景：</strong>${escapeHtml(example.context)}</p>` : ""}${example.explanation ? `<p><strong>思路：</strong>${escapeHtml(example.explanation)}</p>` : ""}${example.conclusion ? `<p><strong>结论：</strong>${escapeHtml(example.conclusion)}</p>` : ""}</li>`).join("")}</ul>`
    : ""));

  parts.push(section("作业与后续安排", list(content.assignments)));
  parts.push(section("课堂问题", list(content.questions)));
  parts.push(section("复习自测", list(content.review_questions, true)));
  parts.push(section("待核对内容", list(content.to_verify)));
  if (content.keywords?.length) parts.push(`<p><strong>关键词</strong>：${content.keywords.map(escapeHtml).join("、")}</p>`);
  return parts.filter(Boolean).join("\n");
}
