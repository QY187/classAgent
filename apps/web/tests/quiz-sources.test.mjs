import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
const require = createRequire(import.meta.url);
function compile(path, overrides = {}) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} };
  new Function("module", "exports", "require", code)(module, module.exports, (name) => overrides[name] || require(name));
  return module.exports;
}
const materials = compile("../lib/materials.ts");
const { quizSourceUrl } = compile("../lib/quizzes.ts", { "./materials": materials });
const source = { course_id: "c", material_id: "m", version: "v1", position: 12, source_status: "current" };
test("小测课件来源保留版本位置，优先于课次录音链接", () => {
  assert.equal(quizSourceUrl({ source_material: source, source_lesson_id: "l", source_start_ms: 0 }), "/courses/c/materials/m?position=12&version=v1");
});
test("替换删除的课件引用禁用跳转，不误跳录音", () => {
  for (const status of ["changed", "unavailable"]) assert.equal(quizSourceUrl({ source_material: { ...source, source_status: status }, source_lesson_id: "l", source_start_ms: 0 }), null);
});
test("存量课堂题时间跳转保持兼容", () => {
  assert.equal(quizSourceUrl({ source_lesson_id: "l", source_start_ms: 42000 }), "/lessons/l/transcript?t=42000");
  assert.equal(quizSourceUrl({ source_lesson_id: null, source_start_ms: 0 }), null);
});
