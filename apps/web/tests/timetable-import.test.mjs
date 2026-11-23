import assert from "node:assert/strict";
import test from "node:test";
import { assessImport } from "../lib/timetable-import.ts";

const semester = { week_count: 20, periods: Array.from({ length: 13 }, () => ({ start: "08:00", end: "08:45" })) };
const entry = { title: "软件工程", weekday: 1, start_period: 1, end_period: 3, start_week: 1, end_week: 20,
  week_pattern: "all", room: "A101", teacher: "", course_id: null, color: "teal" };
const row = (changes = {}, selected = true) => ({ entry: { ...entry, ...changes }, selected, warnings: [], errors: [], status: "ready", raw: "", source: "测试" });

test("导入预览允许单双周共用节次，拒绝实际周次重叠", () => {
  const existing = [{ ...entry, id: "old", week_pattern: "odd" }];
  assert.deepEqual(assessImport([row({ week_pattern: "even" })], existing, semester)[0].errors, []);
  assert.match(assessImport([row({ title: "重叠课程" })], existing, semester)[0].errors[0], /冲突/);
});
test("重复记录可跳过，修改时间后重新计算状态", () => {
  const existing = [{ ...entry, id: "old" }];
  assert.equal(assessImport([row()], existing, semester)[0].duplicate, true);
  assert.equal(assessImport([row({ weekday: 2 })], existing, semester)[0].duplicate, false);
  assert.deepEqual(assessImport([row({ weekday: 2 })], existing, semester)[0].errors, []);
});
test("批内冲突会提示，取消选择冲突行后解除", () => {
  const result = assessImport([row(), row({ title: "另一门课" })], [], semester);
  assert.ok(result.every((item) => item.errors.some((message) => message.includes("本次导入"))));
  assert.deepEqual(assessImport([row(), row({ title: "另一门课" }, false)], [], semester)[0].errors, []);
});
test("缺项、越界及单双周空区间阻止确认导入", () => {
  for (const changes of [{ title: "" }, { weekday: 0 }, { end_period: 14 }, { start_week: 0 }, { end_week: 21 }, { start_week: 2, end_week: 2, week_pattern: "odd" }]) {
    assert.ok(assessImport([row(changes)], [], semester)[0].errors.length > 0);
  }
});
