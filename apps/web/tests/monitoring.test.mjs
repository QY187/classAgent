import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../lib/monitoring.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const module = { exports: {} };
new Function("module", "exports", compiled)(module, module.exports);
const { orderedStages, duration, tokenCoverage } = module.exports;
const stage = (id, parent, timestamp = "2026-11-01T00:00:00Z", ms = 1) => ({
  event: "span.finished", span_id: id, parent_span_id: parent, timestamp, duration_ms: ms,
});

test("阶段按父子树展示，结束顺序及毫秒误差不会将子阶段放在父阶段之前", () => {
  const events = [stage("child", "root", undefined, 1.2), stage("root", null, undefined, 1),
    stage("later-child", "later"), stage("later", "root", "2026-11-01T00:00:01Z")];
  assert.deepEqual(orderedStages(events).map(({ event, depth }) => [event.span_id, depth]),
    [["root", 0], ["child", 1], ["later", 1], ["later-child", 2]]);
});

test("父阶段缺失、循环引用和重复记录不会漏展示或死循环", () => {
  const events = [stage("orphan", "missing"), stage("a", "b"), stage("b", "a"), stage("a", "b")];
  const result = orderedStages(events);
  assert.equal(result.length, 3);
  assert.deepEqual(new Set(result.map(({ event }) => event.span_id)), new Set(["orphan", "a", "b"]));
});

test("无耗时保持未知，Token 总量覆盖不能用仅报告输入的调用代替", () => {
  assert.equal(duration(null), "—");
  assert.equal(duration(0), "0 ms");
  assert.equal(tokenCoverage({ model_calls: 3, usage_reported_calls: 2, total_tokens_reported_calls: 1 }), "1/3 次调用报告总量");
});
