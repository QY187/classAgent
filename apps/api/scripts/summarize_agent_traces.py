"""汇总 JSON 追踪日志；支持 Docker 日志前缀、多个文件及标准输入。"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import json
import math
from pathlib import Path
import sys


def read_records(lines):
    for line in lines:
        start = line.find('{"schema_version":')
        if start < 0:
            continue
        try:
            value = json.loads(line[start:])
        except (ValueError, TypeError):
            continue
        if (isinstance(value, dict) and type(value.get("schema_version")) is int
                and value["schema_version"] == 1 and isinstance(value.get("trace_id"), str)
                and isinstance(value.get("event"), str)):
            yield value


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _latencies(values):
    values = sorted(value for value in values if _number(value))
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    # nearest-rank；不在小样本中插值出不存在的观测。
    return {"count": len(values), "p50_ms": values[math.ceil(len(values) * .5) - 1],
            "p95_ms": values[math.ceil(len(values) * .95) - 1], "max_ms": values[-1]}


def summarize(records, *, request_id=None):
    attempts, finished, spans = set(), {}, {}
    repairs, fallbacks = Counter(), Counter()
    seen = set()
    for record in records:
        if request_id is not None and record.get("request_id") != request_id:
            continue
        attempts.add(record["trace_id"])
        key = (record["trace_id"], record.get("span_id"), record["event"], record.get("timestamp"))
        if key in seen:
            continue
        seen.add(key)
        event = record["event"]
        if event == "request.started":
            attempts.add(record["trace_id"])
        elif event == "request.finished":
            attempts.add(record["trace_id"])
            finished[record["trace_id"]] = record
        elif event == "span.finished" and isinstance(record.get("name"), str):
            spans[(record["trace_id"], record.get("span_id"))] = record
        elif event.endswith(".repair"):
            repairs[record.get("reason", "unknown")] += 1
        elif event.endswith(".fallback"):
            fallbacks[record.get("reason", "unknown")] += 1

    rows = list(finished.values())
    counters = ("model_calls", "model_errors", "tool_calls", "tool_errors", "repair_count",
                "fallback_count", "db_queries", "db_errors", "db_duration_ms", "prompt_tokens",
                "completion_tokens", "total_tokens", "usage_reported_calls", "usage_missing_calls",
                "prompt_tokens_reported_calls", "completion_tokens_reported_calls", "total_tokens_reported_calls")
    totals = {key: round(sum(row[key] for row in rows if _number(row.get(key))), 3) for key in counters}
    stages, models = defaultdict(list), defaultdict(list)
    for record in spans.values():
        stages[record["name"]].append(record)
        if record.get("kind") == "model":
            models[(record.get("provider", "unknown"), record.get("model", "unknown"))].append(record)
    return {
        "attempts": len(attempts), "completed_attempts": len(rows),
        "incomplete_attempts": len(attempts - finished.keys()),
        "request_errors": sum(row.get("status") == "error" for row in rows),
        "outcomes": dict(Counter(row.get("outcome", "unknown") for row in rows)),
        "request_latency": _latencies(row.get("duration_ms") for row in rows),
        "totals": totals, "repair_reasons": dict(repairs), "fallback_reasons": dict(fallbacks),
        "stages": {name: {**_latencies(row.get("duration_ms") for row in group),
                           "errors": sum(row.get("status") == "error" for row in group)}
                   for name, group in sorted(stages.items())},
        "models": [{"provider": provider, "model": model, "calls": len(group),
                    "errors": sum(row.get("status") == "error" for row in group),
                    **{key: sum(row[key] for row in group if _number(row.get(key)))
                       for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
                    "usage_reported_calls": sum(bool(row.get("usage_reported")) for row in group),
                    **{key + "_reported_calls": sum(_number(row.get(key)) for row in group)
                       for key in ("prompt_tokens", "completion_tokens", "total_tokens")}}
                   for (provider, model), group in sorted(models.items())],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="日志文件；不传文件时从标准输入读取")
    parser.add_argument("--request-id", help="仅统计指定业务请求，包含它的多次尝试")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        streams = [stack.enter_context(Path(path).open(encoding="utf-8-sig", errors="replace"))
                   for path in args.files] or [sys.stdin]
        report = summarize(read_records(line for stream in streams for line in stream), request_id=args.request_id)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    latency, totals = report["request_latency"], report["totals"]
    print("# Agent 请求追踪统计\n")
    print(f"请求尝试：{report['attempts']}；已结束：{report['completed_attempts']}；未结束：{report['incomplete_attempts']}；异常：{report['request_errors']}。")
    print(f"\n总耗时 P50 / P95：{latency['p50_ms']} / {latency['p95_ms']} ms。")
    print(f"\n模型调用 / 异常：{totals['model_calls']} / {totals['model_errors']}；工具调用 / 异常：{totals['tool_calls']} / {totals['tool_errors']}。")
    print(f"\n修复：{totals['repair_count']}；降级：{totals['fallback_count']}；SQL：{totals['db_queries']} 次，{totals['db_duration_ms']} ms。")
    print(f"\n已报告 token 小计：输入 {totals['prompt_tokens']}、输出 {totals['completion_tokens']}、总量 {totals['total_tokens']}。")
    print(f"\n用量有报告 / 完全缺报调用：{totals['usage_reported_calls']} / {totals['usage_missing_calls']}。分字段报告数见 JSON 或逐模型表；缺失部分不估算。")
    print("\n| 阶段 | 次数 | 异常 | P50 ms | P95 ms |\n| --- | ---: | ---: | ---: | ---: |")
    for name, row in report["stages"].items():
        print(f"| {name} | {row['count']} | {row['errors']} | {row['p50_ms']} | {row['p95_ms']} |")
    print("\n| 模型 | 调用 | 输入/输出/总 token | 输入/输出/总量有报告次数 |\n| --- | ---: | --- | --- |")
    for row in report["models"]:
        print(f"| {row['provider']}/{row['model']} | {row['calls']} | {row['prompt_tokens']}/{row['completion_tokens']}/{row['total_tokens']} | {row['prompt_tokens_reported_calls']}/{row['completion_tokens_reported_calls']}/{row['total_tokens_reported_calls']} |")
    print("\n业务结果：" + json.dumps(report["outcomes"], ensure_ascii=False))
    print("\n修复原因：" + json.dumps(report["repair_reasons"], ensure_ascii=False))
    print("\n降级原因：" + json.dumps(report["fallback_reasons"], ensure_ascii=False))
    print("\n口径：按 trace_id 统计尝试；请求总量只汇总完整 request.finished，阶段与模型表可含未结束请求的已结束调用。父子阶段耗时含嵌套部分，不相加。HTTP/SSE 建连时间不等于回答生成时间；token 为已报告小计，不是费用。")


if __name__ == "__main__":
    main()
