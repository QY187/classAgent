import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(path, overrides = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const result = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  new Function("module", "exports", "require", result.outputText)(module, module.exports, (name) => overrides[name] || require(name));
  return module.exports;
}
const materials = compile("../lib/materials.ts");
const presentation = compile("../lib/chat-presentation.ts", { "./materials": materials });
const CitationList = compile("../components/chat/ChatCitationList.tsx", { "../../lib/chat-presentation": presentation }).default;
const material = { id: 1, source_type: "material", course_id: "c", material_id: "m", filename: "<课件>.pdf",
  lesson_id: null, lesson_title: "课程公共资料", start_ms: null, position: 12, version: "v", locator_label: "第 8 页",
  snippet: "<script>用户资料</script>", source_status: "current" };
const render = (citations) => renderToStaticMarkup(createElement(CitationList, { citations }));

test("课件引用保留版本与位置，内容转义且不会生成录音时间链接", () => {
  const html = render([material]);
  assert.match(html, /第 8 页/);
  assert.match(html, /\/courses\/c\/materials\/m\?position=12&amp;version=v/);
  assert.ok(!html.includes("/transcript") && !html.includes("<script>"));
  assert.match(html, /&lt;课件&gt;/);
});

test("失效课件禁用跳转，换版课件明确提示并能打开当前资料", () => {
  const deleted = render([{ ...material, source_status: "unavailable" }]);
  assert.match(deleted, /来源已删除或当前不可访问/);
  assert.ok(!deleted.includes("href="));
  const changed = render([{ ...material, source_status: "changed" }]);
  assert.match(changed, /来源版本已变化/);
  assert.match(changed, /href=/);
});

test("旧录音引用保留原有时间跳转，可与课件引用同时展示", () => {
  const html = render([material, { id: 2, lesson_id: "l", lesson_title: "第一讲", start_ms: 61000, snippet: "课堂内容" }]);
  assert.match(html, /\/lessons\/l\/transcript\?t=61000/);
  assert.match(html, /01:01/);
  assert.match(html, /2 条引用/);
});


test("来源包含课程与时间范围，带来源复制保留编号、摘录与链接", () => {
  const transcript={ id:2,lesson_id:"l",lesson_title:"第一讲",course_name:"数据结构",start_ms:3600000,end_ms:3605000,snippet:"叶子没有孩子" };
  const html=render([transcript]);
  assert.match(html,/数据结构 → 第一讲/); assert.match(html,/01:00:00–01:00:05/);
  const text=presentation.answerWithSources("结论 [2]",[transcript,{...material,source_status:"unavailable"}],"http://localhost:3000");
  assert.match(text,/\[2\] 数据结构/); assert.match(text,/http:\/\/localhost:3000\/lessons\/l\/transcript\?t=3600000/);
  assert.match(text,/来源已删除或当前不可访问/); assert.ok(!text.includes('/materials/m'));
});
