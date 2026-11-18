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

test("默认只导出纪要和文字，答案与原文件需要明确勾选", () => {
  const { defaultExportContents, selectedExportLabels } = load();
  assert.deepEqual(selectedExportLabels(defaultExportContents), ["智能纪要", "文字记录"]);
  const onlyQuiz = { summaries: false, transcripts: false, knowledge: false, quizzes: true, answers: false, audio: false, materials: false };
  assert.deepEqual(selectedExportLabels(onlyQuiz), ["小测题目"]);
  assert.deepEqual(selectedExportLabels({ ...onlyQuiz, answers: true }), ["小测题目、答案与解析"]);
});
