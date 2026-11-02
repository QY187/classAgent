import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(path, customRequire = require) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const result = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  new Function("module", "exports", "require", result.outputText)(module, module.exports, customRequire);
  return module.exports;
}
const Card = compile("../components/chat/ChatFailureCard.tsx").default;
const { chatFailureMessage } = compile("../lib/chat-errors.ts", () => ({ errorMessage: error => error.message }));

test("失败原因直接显示在对话卡片中，包含请求编号且不会渲染异常 HTML", () => {
  const html = renderToStaticMarkup(createElement(Card, { reason: "理解问题阶段失败：AI 服务未在规定时间内响应。<script>unsafe</script>", requestId: "request-1" }));
  assert.ok(html.includes("本次回答失败") && html.includes("失败原因：") && html.includes("理解问题阶段失败"));
  assert.ok(html.includes("request-1") && !html.includes("<script>"));
});

test("旧消息没有具体原因时明确说明未知，不编造失败归因", () => {
  const html = renderToStaticMarkup(createElement(Card, { reason: null, requestId: "old-request" }));
  assert.ok(html.includes("暂时无法确认具体原因"));
});

test("浏览器超时和网络中断不能被说成服务器处理已失败", () => {
  assert.ok(chatFailureMessage(new DOMException("private", "TimeoutError")).includes("暂时无法确认"));
  assert.ok(chatFailureMessage(new TypeError("private network response")).includes("连接失败"));
  assert.ok(!chatFailureMessage(new TypeError("private network response")).includes("private"));
  assert.equal(chatFailureMessage(new Error("理解问题阶段失败：AI 服务触发请求限制。")), "理解问题阶段失败：AI 服务触发请求限制。");
});
