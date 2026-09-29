import assert from "node:assert/strict";
import test from "node:test";
import { collectSpeechResults } from "../lib/speech-results.ts";

const result = (transcript, isFinal) => ({ 0: { transcript }, isFinal });

test("同一识别会话反复发送最终结果时只保存一次", () => {
  const accepted = new Set();

  assert.deepEqual(collectSpeechResults([result("1234567。", true)], accepted), {
    finalTexts: ["1234567。"], interim: "",
  });
  assert.deepEqual(collectSpeechResults([
    result("1234567。", true), result("7654", false),
  ], accepted), { finalTexts: [], interim: "7654" });
  assert.deepEqual(collectSpeechResults([
    result("1234567。", true), result("7654321。", true),
  ], accepted), { finalTexts: ["7654321。"], interim: "" });

  accepted.clear();
  assert.deepEqual(collectSpeechResults([result("新的会话。", true)], accepted).finalTexts, ["新的会话。"]);
});
