import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/chat-stream.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

function client(chunks, onRequest = () => {}) {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { for (const chunk of chunks) controller.enqueue(chunk); controller.close(); },
    cancel() { cancelled = true; },
  });
  const module = { exports: {} };
  new Function("module", "exports", "require", compiled)(module, module.exports, () => ({
    authorizedResponse: async (path, options) => { onRequest(options); return new Response(stream); },
  }));
  return module.exports.streamAnswer;
}

const bytes = (text) => new TextEncoder().encode(text);

test("中文 UTF-8 与 SSE 在任意字节断包时仍按序显示并返回最终历史", async () => {
  const text = ': keepalive\n\nevent: answer\ndata: {"answer":"二叉树 [1]","citations":[{"id":1}]}\n\nevent: done\ndata: {"messages":[{"content":"完整回答"}]}\n\n';
  const data = bytes(text);
  const previews = [];
  const result = await client(Array.from(data, (byte) => Uint8Array.of(byte)))("c", "问题", "r", (value) => previews.push(value));
  assert.deepEqual(previews, [{ answer: "二叉树 [1]", citations: [{ id: 1 }] }]);
  assert.deepEqual(result, { messages: [{ content: "完整回答" }] });
});

test("错误事件和没有完成标记的连接不会误认为成功", async () => {
  await assert.rejects(client([bytes('event: error\ndata: {"detail":"模型中断"}\n\n')])("c", "问题", "r", () => {}), /模型中断/);
  await assert.rejects(client([bytes('event: answer\ndata: {"answer":"部分回答","citations":[]}\n\n')])("c", "问题", "r", () => {}), /连接已中断/);
});

test("兼容 CRLF 事件和连续回答快照", async () => {
  const previews = [];
  const data = bytes('event: answer\r\ndata: {"answer":"一","citations":[]}\r\n\r\nevent: answer\r\ndata: {"answer":"一二","citations":[]}\r\n\r\nevent: done\r\ndata: {"messages":[]}\r\n\r\n');
  await client([data])("c", "问题", "r", (value) => previews.push(value.answer));
  assert.deepEqual(previews, ["一", "一二"]);
});

test("只有后端确认问题开始后才通知可停止，并传递取消信号", async () => {
  const controller = new AbortController();
  const order = [];
  const data = bytes('event: status\ndata: {"message":"准备中"}\n\nevent: status\ndata: {"ready":true}\n\nevent: answer\ndata: {"answer":"已校验结论","citations":[]}\n\nevent: done\ndata: {"messages":[]}\n\n');
  await client([data], (options) => assert.equal(options.signal, controller.signal))("c", "问题", "r", () => order.push("answer"), {
    signal: controller.signal, onReady: () => order.push("ready"),
  });
  assert.deepEqual(order, ["ready", "answer"]);
});
