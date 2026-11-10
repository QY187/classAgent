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
const MarkdownView = compile("../components/MarkdownView.tsx");
const MessageList = compile("../components/chat/ChatMessageList.tsx", name => {
  if (name === "../MarkdownView") return MarkdownView;
  if (name.startsWith("./Chat")) return { default: () => null };
  if (name === "next/link") return { default: ({ children, href }) => createElement("a", { href }, children) };
  return require(name);
}).default;

function render(role, content) {
  return renderToStaticMarkup(createElement(MessageList, { generating: false, username: "测试用户", conversationId: "test",
    messages: [{ id: "answer", role, status: "completed", content, citations: [], created_at: "2026-11-02T00:00:00Z" }] }));
}

test("助手的出处、解释和学习记录呈现为标题与列表，不显示Markdown标记", () => {
  const html = render("assistant", "**内容出处**\n\n《数据结构》 · 第二讲 [1]\n\n**课堂说明**\n\n- 每个节点最多有两个孩子。 [2]\n- 左右孩子不能随意交换。 [3]\n\n**学习记录**\n\n没有需要复习的知识点。");
  assert.ok(html.includes("<strong>内容出处</strong>") && html.includes("<strong>课堂说明</strong>"));
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.ok(html.includes("没有需要复习的知识点") && !html.includes("**"));
});

test("原文与用户输入中的HTML仍为文字，用户消息保留字面输入", () => {
  const assistant = render("assistant", "**说明**\n\n<script>alert('unsafe')</script>\n<img src=x onerror=alert(1)>");
  assert.ok(!assistant.includes("<script>") && !assistant.includes("<img "));
  assert.ok(assistant.includes("&lt;script&gt;") && assistant.includes("&lt;img"));
  const user = render("user", "**不要把这句话当格式**");
  assert.ok(user.includes("**不要把这句话当格式**") && !user.includes("<strong>"));
});

test("空回答不生成空的富文本容器", () => {
  assert.ok(!render("assistant", "").includes('class="markdown-body"'));
});

test("回答中的Markdown表格保留表头、对齐和行列，支持窄屏滚动", () => {
  const html = render("assistant", "| 方法 | 根节点 |\n| :--- | ---: |\n| **先序** | 最先 |\n| 中序 | 左子树之后 |\n\n表格后的说明");
  assert.ok(html.includes('class="markdown-table-scroll"'));
  assert.ok(html.includes('role="region"') && html.includes('tabindex="0"'));
  assert.equal((html.match(/<th /g) || []).length, 2);
  assert.equal((html.match(/<td /g) || []).length, 4);
  assert.ok(html.includes('text-align:right'));
  assert.ok(html.includes("<strong>先序</strong>"));
  assert.ok(html.includes("表格后的说明"));
});

test("普通竖线不被误识别为表格，单列和转义竖线可正确显示", () => {
  assert.ok(!render("assistant", "a | b\n普通说明").includes("<table>"));
  const html = render("assistant", "| 标题 |\n| --- |\n| 左\\|右 |");
  assert.equal((html.match(/<th /g) || []).length, 1);
  assert.equal((html.match(/<td /g) || []).length, 1);
  assert.ok(html.includes("左|右"));
});

test("表格单元格的HTML仍被转义，缺失的列保持结构", () => {
  const html = render("assistant", "| A | B |\n| --- | --- |\n| <img src=x onerror=alert(1)> |\n| 安全 | <script>alert(1)</script> |");
  assert.equal((html.match(/<td /g) || []).length, 4);
  assert.ok(!html.includes("<img ") && !html.includes("<script>"));
  assert.ok(html.includes("&lt;img") && html.includes("&lt;script&gt;"));
});
