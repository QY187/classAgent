import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
const compiled = ts.transpileModule(readFileSync(new URL("../lib/course-export.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
function load(authorizedResponse) {
  const module = { exports: {} };
  new Function("require", "module", "exports", compiled)(() => ({ authorizedResponse }), module, module.exports);
  return module.exports;
}
test("课程ZIP文件名不会形成路径或Windows非法文件名", () => {
  const { courseZipName } = load();
  assert.equal(courseZipName("数据/结构:第一课"), "数据_结构_第一课-课程资料.zip");
  assert.equal(courseZipName("  "), "课堂-课程资料.zip");
});
test("只向当前课程传递范围，不把HTML错误页保存为ZIP", async () => {
  let sent;
  const { downloadCourseArchive } = load(async (...args) => { sent = args; return new Response("login", { headers: { "Content-Type": "text/html" } }); });
  await assert.rejects(downloadCourseArchive("c", "课程", { lesson_ids: ["lesson"] }, new AbortController().signal), /未收到可用的ZIP/);
  assert.equal(sent[0], "/courses/c/export");
  assert.deepEqual(JSON.parse(sent[1].body), { lesson_ids: ["lesson"] });
});
test("截断或错误响应不生成伪ZIP下载", async () => {
  const { downloadCourseArchive } = load(async () => new Response("error", { headers: { "Content-Type": "application/zip" } }));
  await assert.rejects(downloadCourseArchive("c", "课程", { lesson_ids: null }, new AbortController().signal), /导出文件不完整/);
});

test("默认只包含四项PDF内容并全部勾选", () => {
  const { defaultExportContents, selectedExportLabels, exportContentChoices } = load();
  assert.deepEqual(selectedExportLabels(defaultExportContents), ["智能纪要", "知识点", "小测题目", "文字记录"]);
  assert.equal(Object.keys(defaultExportContents).length, 4);
  assert.ok(Object.values(defaultExportContents).every(Boolean));
  assert.ok(exportContentChoices.every(choice => choice.description.startsWith("PDF")));
  assert.deepEqual(selectedExportLabels({ summaries: false, knowledge: false, quizzes: true, transcripts: false }), ["小测题目"]);
});

test("PDF预览使用已认证请求并保留范围及文档路径", async () => {
  const calls = [];
  const { previewCourseExport } = load(async (...args) => { calls.push(args); return calls.length === 1
    ? Response.json({ documents: ["课程目录.pdf", "001_课堂/智能纪要.pdf"] })
    : new Response("%PDF-real", { headers: { "Content-Type": "application/pdf" } }); });
  const options = { lesson_ids: ["lesson"], contents: { summaries: true, knowledge: false, quizzes: false, transcripts: false } };
  const signal = new AbortController().signal;
  assert.deepEqual(await previewCourseExport("c", options, signal), ["课程目录.pdf", "001_课堂/智能纪要.pdf"]);
  assert.equal(await (await previewCourseExport("c", options, signal, "001_课堂/智能纪要.pdf")).text(), "%PDF-real");
  assert.equal(calls[1][0], "/courses/c/export/preview?document=" + encodeURIComponent("001_课堂/智能纪要.pdf"));
  assert.deepEqual(JSON.parse(calls[1][1].body), options);
  assert.equal(calls[1][1].signal, signal);
});

test("PDF预览拒绝错误类型和截断文件，保留接口失败", async () => {
  for (const response of [new Response("login", { headers: { "Content-Type": "text/html" } }), new Response("broken", { headers: { "Content-Type": "application/pdf" } })]) {
    const { previewCourseExport } = load(async () => response);
    await assert.rejects(previewCourseExport("c", { lesson_ids: null }, new AbortController().signal, "课程目录.pdf"), /PDF/);
  }
  const { previewCourseExport } = load(async () => { throw new Error("课程不存在"); });
  await assert.rejects(previewCourseExport("c", { lesson_ids: null }, new AbortController().signal), /课程不存在/);
});
