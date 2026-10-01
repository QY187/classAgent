import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/summary-html.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
new Function("module", "exports", compiled)(module, module.exports);
const { summaryToHtml } = module.exports;

test("纪要章节保持连续编号，主题、概念和案例保留各自的内容层级", () => {
  const html = summaryToHtml({
    chapter_flow: [{ title: "第一章", summary: "概述" }, { title: "第二章", summary: "性质" }],
    topics: [{ title: "节点数", summary: "计算节点", points: ["逐层计算", "求和"], takeaway: "注意层数" }],
    key_concepts: [{ term: "叶子节点", definition: "没有孩子", importance: "用于计数" }],
    examples: [{ title: "例题一", context: "已知高度", explanation: "逐层相加", conclusion: "得到总数" }],
  });

  assert.match(html, /<h3>章节脉络<\/h3><ol><li><strong>第一章<\/strong><p>概述<\/p><\/li><li><strong>第二章<\/strong><p>性质<\/p><\/li><\/ol>/);
  assert.match(html, /<h3>主题与重点<\/h3><ul><li><strong>节点数<\/strong><p>计算节点<\/p><ul><li>逐层计算<\/li><li>求和<\/li><\/ul><p><strong>记住：<\/strong>注意层数<\/p><\/li><\/ul>/);
  assert.match(html, /<h3>核心概念<\/h3><ul><li><strong>叶子节点<\/strong>：没有孩子<p><strong>重要性：<\/strong>用于计数<\/p><\/li><\/ul>/);
  assert.match(html, /<h3>例题与案例<\/h3><ul><li><strong>例题一<\/strong><p><strong>背景：<\/strong>已知高度<\/p><p><strong>思路：<\/strong>逐层相加<\/p><p><strong>结论：<\/strong>得到总数<\/p><\/li><\/ul>/);
});

test("纪要内容按纯文本转义", () => {
  const html = summaryToHtml({ topics: [{ title: "<img src=x>", points: ["A & B"] }] });
  assert.ok(!html.includes("<img"));
  assert.match(html, /&lt;img src=x&gt;/);
  assert.match(html, /A &amp; B/);
});
