import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import ts from 'typescript';
const require = createRequire(import.meta.url);
function compile(file, overrides = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', compiled)(module, module.exports, name => overrides[name] || require(name));
  return module.exports;
}
const styles = compile('../lib/export-styles.ts');
const summary = compile('../lib/summary-html.ts');
const { buildLessonHtml, buildLessonMarkdown, buildLessonText, buildTranscriptText, exportFilename } = compile('../lib/export.ts', { './export-styles': styles, './summary-html': summary });
const fixture = { lesson: { title: '二叉树与遍历', lesson_date: '2026-11-21' }, summary: {
  overview: '梳理二叉树的结构。', learning_goals: ['掌握遍历'], chapter_flow: [{ title: '定义', time_range: '00:00 - 10:00', summary: '每个节点最多两个孩子' }], topics: [{ title: '遍历', summary: '访问节点', points: ['先序先访问根'], takeaway: '明确访问顺序' }], key_concepts: [{ term: '叶子', definition: '没有孩子', importance: '用于计算' }], key_takeaways: ['遍历次序不同'], teacher_emphasis: ['不要混淆层与高度'], examples: [{ title: '示例', context: '给定一棵树', explanation: '递归访问', conclusion: '获得序列' }], assignments: ['完成习题'], questions: ['如何求高度？'], review_questions: ['描述先序'], to_verify: ['复杂度待核对'], keywords: ['二叉树', '遍历'] }, segments: [{ speaker: 'speaker_1', start_ms: 3600000, end_ms: 3609000, text: '原文第一段。\n第二行。' }, { speaker: 'speaker_2', start_ms: 3610000, end_ms: 3615000, text: '同学提问。' }], speakerAliases: { speaker_1: '老师', speaker_2: '同学A' } };

test('PDF使用真实标题列表、完整纪要与独立文字记录，不打印Markdown语法', () => {
  const html = buildLessonHtml(fixture);
  assert.match(html, /<h1>二叉树与遍历<\/h1>/);
  assert.match(html, /<h3>章节脉络<\/h3><ol>/);
  assert.match(html, /class="transcript new-page"/);
  for (const value of ['学习目标', '关键结论', '老师强调', '例题与案例', '作业与后续安排', '课堂问题', '复习自测', '待核对内容', '关键词', '老师', '同学A']) assert.ok(html.includes(value), value);
  assert.ok(!html.includes('## 智能纪要') && !html.includes('**概览**'));
  assert.match(html, /01:00:00 - 01:00:09/);
  assert.match(html, /counter\(pages\)/);
});

test('Markdown和TXT保留完整内容、段落、时间范围及说话人别名', () => {
  const md = buildLessonMarkdown(fixture), text = buildLessonText(fixture), transcript = buildTranscriptText(fixture);
  assert.match(md, /### 001 · 老师\n\n> 01:00:00 - 01:00:09\n\n原文第一段/);
  assert.match(text, /原文第一段。\n第二行。\n\n002/);
  assert.ok(!text.includes('**') && !text.includes('###'));
  assert.ok(transcript.includes('上课日期：2026-11-21') && !transcript.includes('梳理二叉树的结构'));
});

test('用户标题和原文安全转义，不在打印文档中执行HTML或加载外部内容', () => {
  const html = buildLessonHtml({ ...fixture, lesson: { title: '</title><script>bad()</script>' }, segments: [{ ...fixture.segments[0], text: '<img src=x onerror=bad()> & 内容' }] });
  assert.ok(!html.includes('<script>') && !html.includes('<img'));
  assert.ok(html.includes('&lt;img') && html.includes('&amp; 内容'));
  assert.match(html, /Content-Security-Policy/);
});

test('空资料有明确空状态，不生成空白附录页；下载文件名兼容Windows', () => {
  const html = buildLessonHtml({ lesson: { title: '空课次' }, summary: null, segments: [] });
  assert.ok(html.includes('暂无智能纪要') && html.includes('暂无文字记录'));
  assert.ok(!html.includes('class="transcript new-page"'));
  assert.equal(exportFilename('课堂:一/二?'), '课堂_一_二_-课堂资料');
  assert.equal(exportFilename('   '), '课堂-课堂资料');
});
