import assert from "node:assert/strict";
import test from "node:test";
import { overlappingEntries } from "../lib/timetable.ts";

test("重叠课程包含间接交叠，相邻节次不合并且不修改输入", () => {
  const input = [
    { id: "d", title: "D", start_period: 8, end_period: 10 },
    { id: "b", title: "B", start_period: 3, end_period: 5 },
    { id: "a", title: "A", start_period: 1, end_period: 3 },
    { id: "c", title: "C", start_period: 5, end_period: 7 },
  ];
  assert.deepEqual(overlappingEntries(input).map((items) => items.map((item) => item.id)), [["a", "b", "c"], ["d"]]);
  assert.deepEqual(input.map((item) => item.id), ["d", "b", "a", "c"]);
});

test("全天实践叠放在同一组，空课表返回空组", () => {
  const input = ["实习", "课程设计"].map((title) => ({ title, start_period: 1, end_period: 10 }));
  assert.equal(overlappingEntries(input).length, 1);
  assert.equal(overlappingEntries(input)[0].length, 2);
  assert.deepEqual(overlappingEntries([]), []);
});
