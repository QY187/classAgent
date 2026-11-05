import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
function compile(path) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const result = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  new Function("module", "exports", "require", result.outputText)(module, module.exports, require);
  return module.exports;
}
const { chatRequestIdentity } = compile("../lib/chat-models.ts");
const ModelSelect = compile("../components/chat/ChatModelSelect.tsx").default;
const last = { role: "user", content: "解释二叉树", request_id: "original", status: "failed", model: { id: "alpha" } };

test("显式重试固定原模型，切换模型后同样的问题生成新请求", () => {
  assert.deepEqual(chatRequestIdentity(last, last.content, "beta", "original"), { requestId: "original", modelId: "alpha" });
  assert.deepEqual(chatRequestIdentity(last, last.content, "alpha", undefined, () => "new"), { requestId: "original", modelId: "alpha" });
  assert.deepEqual(chatRequestIdentity(last, last.content, "beta", undefined, () => "new"), { requestId: "new", modelId: "beta" });
  assert.throws(() => chatRequestIdentity(last, "另一问题", "alpha", "original"), /已有新消息/);
});

test("旧消息重试仍使用默认模型，已完成消息再次提问不复用请求编号", () => {
  assert.deepEqual(chatRequestIdentity({ ...last, model: null }, last.content, "beta", "original"), { requestId: "original", modelId: "default" });
  assert.equal(chatRequestIdentity({ ...last, status: "completed" }, last.content, "alpha", undefined, () => "new").requestId, "new");
});

const models = [{ id: "default", label: "默认模型", available: true }, { id: "alpha", label: '<img src=x onerror="alert(1)">', available: true },
  { id: "disabled", label: "未配置模型", available: false }];
function render(overrides = {}) {
  return renderToStaticMarkup(createElement(ModelSelect, { models, value: "alpha", disabled: false, loading: false,
    error: "", onChange() {}, onRetry() {}, ...overrides }));
}

test("模型选择展示真实选中项，转义名称并禁用无凭证项", () => {
  const html = render();
  assert.match(html, /aria-label="选择 Agent 模型"/);
  assert.match(html, /value="alpha" selected=""/);
  assert.ok(html.includes("&lt;img") && !html.includes("<img"));
  assert.match(html, /value="disabled" disabled=""/);
});

test("正在生成时禁用选择，下线的选择不会悄悄变成默认模型", () => {
  assert.match(render({ disabled: true }), /<select[^>]*disabled=""/);
  const html = render({ value: "removed" });
  assert.ok(html.includes("原模型不可用，请选择"));
  assert.match(html, /value="removed" disabled="" selected=""/);
});

test("目录读取失败提供重试，错误内容按纯文本显示", () => {
  const html = render({ error: "<script>错误</script>" });
  assert.match(html, /role="alert"/);
  assert.ok(html.includes("重试") && html.includes("&lt;script&gt;") && !html.includes("<script>"));
  assert.match(html, /<select[^>]*disabled=""/);
});
