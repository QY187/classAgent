# Agent 请求级追踪与指标统计

更新时间：2026-11-01。

## 1. 范围与入口

普通聊天接口和 SSE 聊天接口最终都调用 `send_message`，在这里建立请求追踪；该请求内的语义规划、模型协议适配、工具执行、RAG 检索、回答核验、数据库保存共享同一追踪上下文。SSE 在后台线程执行真正的业务请求，由该线程建立独立上下文，页面断开连接不提前宣告后台任务结束。

本次为本地实现，发布前线上仍使用上一版。没有新增依赖或修改数据库表，未改变业务工具授权、模型提示词正文、模型重试预算或检索参数。

| 字段 | 含义 |
| --- | --- |
| `request_id` | 前端发送的业务请求编号；失败后重试或幂等重放保持不变 |
| `conversation_id` | 对话编号；与 `request_id` 一起定位一条业务请求 |
| `trace_id` | 每次进入业务请求新建的服务端随机编号；重试有新的 trace |
| `span_id` / `parent_span_id` | 同一 trace 内的阶段和父阶段编号 |
| `timestamp` | UTC ISO 时间，带时区 |
| `schema_version` | 日志协议版本，当前为 `1` |

SSE 首个 `status` 事件增加 `request_id`，原有事件名及后续回答结构保持兼容。`trace_id` 是服务端排障字段，不作为用户权限凭据；查询仍须经过服务端鉴权。

## 2. 记录的阶段

| 阶段 | 说明 |
| --- | --- |
| `request` | 一次业务调用的总范围，包含重放、失败和取消 |
| `intent.context` | 读取当前绑定和可见实体样本 |
| `intent.plan` | 读取计划快照或生成计划；`cached` 区分是否复用 |
| `intent.resolve` | 实际规划、类型校验及有界修复，记录提示词摘要 |
| `agent.execute` / `agent.round` | 工具循环及每轮模型选择，记录轮次、预算和提示词摘要 |
| `model.chat` | 规划、工具选择或查询改写调用的实际模型适配入口 |
| `tool.dispatch` / `tool.execute` | 调用编号、已注册工具名、执行耗时和固定错误码 |
| `rag.retrieve` | 混合检索整体、查询变体数和候选数量 |
| `rag.rewrite` / `rag.load_candidates` | 查询改写及授权范围内的候选加载 |
| `rag.vector_recall` / `rag.bm25` / `rag.fusion` | 向量、词法召回及融合 |
| `rag.rerank` | 云端或本地重排策略、实际重排数量 |
| `model.embedding` / `model.rerank` / `model.quiz` | 向量批次、云端重排和小测生成的模型边界 |
| `rag.keyword_fallback` | 未命中子块后的原文关键词回退 |
| `answer.validate` / `answer.compose` | 最终响应解析、证据核验及业务结果组装 |
| `request.persist` / `request.fail_persist` | 成功消息、待办或失败状态的保存 |

每阶段输出 `span.started` 和 `span.finished`，结束记录包含 `duration_ms`。同一 `model.chat` 的父阶段说明用途，不通过记录提问正文识别用途。工具返回 `ok=false` 时即使没有抛出 Python 异常，也计入 `tool_errors`。真正到达模型适配入口的尝试计入 `model_calls`，包括未配置、超时及输出无效的尝试，不等同于供应商实际计费请求数。

候选统计定义：`candidate_limit` 是每路召回上限；`vector_count` 为向量路合并后的唯一子块数；`lexical_count` 为词法候选数；`fused_count` 为融合后唯一子块数；`rerank_count` 为当前重排逻辑输出数；`selected_count` 为去重和父块限额后返回数。当前云端重排与本地重排的候选处理逻辑保持原样，日志展示实际数量，不能把每路上限解释成唯一候选总数。

## 3. 请求汇总与异常口径

每次正常退出或可捕获异常都会输出 `request.finished`，记录：

- 请求总耗时、业务 `outcome`，以及 `cached` / `retry` 状态；没有触发的字段可以省略。
- `model_calls` / `model_errors`、`tool_calls` / `tool_errors`。
- `repair_count` / `fallback_count`。
- `db_queries` / `db_errors` / `db_duration_ms`。
- `prompt_tokens` / `completion_tokens` / `total_tokens` 的已报告小计。
- `usage_reported_calls` / `usage_missing_calls` 及各 token 字段的 `*_reported_calls`。

`status=ok` 表示业务函数正常返回，不表示所有子任务均成功；还要看 `outcome`、`tool_errors` 和降级事件。取消记录 `status=cancelled` / `outcome=cancelled`；HTTP 异常记录固定状态码，4xx 对应 `rejected`，其他异常对应 `failed`。已经完成的幂等请求重放为 `outcome=replayed`，不会再次计入模型或工具调用。

模型输出格式修复和工具循环补全记录为 `intent.repair` / `agent.repair`，固定原因包括 `invalid_plan`、`missing_queries`、`missing_actions`、`missing_queries_after_write`、`invalid_final`。用户主动重试通过请求汇总中的 `retry=true` 和同一 `request_id` 关联。

RAG 降级记录为 `rag.fallback`，原因包括 `rewrite_failed`、`invalid_rewrite`、`vector_failed`、`rerank_failed`、`empty_rerank`、`no_chunks_keyword_search`。配置关闭、未配置重排或没有候选时记录 `rag.rerank_skipped`，与服务调用失败区分；本地重排结果仍由 `rag.rerank.strategy=local` 表示。回答格式失败后使用真实证据恢复记录为 `answer.fallback`。

阶段异常只记录类型和固定原因码，不记录异常文本、供应商响应体或 traceback。模型调用异常在模型阶段记一次；工具失败在工具阶段记一次，两类计数表示不同层级，不能相加解释为失败请求数。

## 4. 数据库与 token 的限制

数据库使用 SQLAlchemy 执行事件累计，成功和失败的 SQL 都只计一次；不记录 SQL 字符串、绑定参数或查询结果。没有活动聊天追踪时不输出数据库指标。阶段内的 SQL 时间包含其子阶段内的 SQL；根请求的 SQL 汇总不会重复累计。指标是客户端 SQL 执行耗时，不是服务器纯计算耗时，也不包含连接池等待、事务 commit/rollback 的完整耗时或 ORM 组装成本。

模型用量仅来自响应中的非负整数 `usage` 字段。完全缺报记入 `usage_missing_calls`；只报告总量或输入量时，其他字段不推算，按字段报告数识别覆盖情况。请求的 token 总量可能只是已报告部分。各模型 tokenizer 和计费口径不同，跨模型累加只能视为粗粒度用量，费用需要单独引入版本化单价及缓存等计费字段，本次不计算金额。

提示词摘要是静态意图/执行提示词的 SHA-256 前 16 位；不包含用户问题、课堂资料、动态实体、API 密钥或模型回答。它帮助识别静态提示变化，不代替完整的 Prompt、Schema 和模型配置版本管理。

## 5. 查看与统计

启动 API 后 `classagent.trace` 会向标准错误输出每行一个 JSON，Docker 可统一收集。发布后在实际发布目录查看最近日志：

```bash
docker compose -p classagentprod --env-file .env.production -f docker-compose.prod.yml -f docker-compose.release.yml logs --no-color --since 1h api
```

日志统计脚本为 `apps/api/scripts/summarize_agent_traces.py`，只使用 Python 标准库。支持 Docker 服务名前缀，忽略普通日志和不完整 JSON，按 trace/span 去重。将日志导出到本地后，在仓库根目录运行：

```powershell
python apps/api/scripts/summarize_agent_traces.py test-results/agent-traces.log
python apps/api/scripts/summarize_agent_traces.py test-results/agent-traces.log --request-id <请求编号>
python apps/api/scripts/summarize_agent_traces.py test-results/agent-traces.log --format json
```

也可以通过标准输入管道传入。输出请求总耗时 P50/P95、阶段耗时、模型/工具调用和错误、SQL、token 已报告小计、业务结果、修复与降级原因。分位数使用 nearest-rank；没有样本时为 `null`，不生成虚假耗时。

统计按 `trace_id` 计算尝试次数，同一个业务请求的重试可以有多条 trace。请求计数和 token 小计只使用完整 `request.finished`，阶段及模型表可保留未结束请求中已经完成的调用；若日志截取范围不完整，两者可能不同。进程崩溃、强制退出或日志丢失可能缺少结束事件，脚本单独显示未结束尝试，不能把它们计入成功率。父子阶段耗时有包含关系，不相加；首个 SSE 状态事件不是首个答案 token，当前没有输出流式 token 的首字耗时指标。

## 6. 安全与未覆盖项

追踪只允许明确列出的指标字段；不写入提问、回答、课程/课次名称、工具参数与结果、SQL/参数、供应商错误文本、密钥或思考内容。不支持的工具名使用 `unknown` 代替，异常标识字符串规范化为 `invalid`。日志包含用户、对话和资料的后端标识，应沿用服务器运维日志访问控制，日志保留与轮转由部署环境配置。

当前未开放追踪查询 API、管理页面或数据库存储，也未接入集中式 Trace 平台或自动告警。范围从业务 `send_message` 开始，不覆盖之前的鉴权/HTTP 建连，也不包括独立 RAG 接口和 Celery 后台转写跨进程追踪；单独调用工具或检索时，只有处于活动请求追踪中才输出阶段日志。本次不为补充观测改变原有业务事务、工具权限和执行顺序。

## 7. 本次验证

2026-11-01：新增 16 项专项测试通过，覆盖父子阶段、线程和异步上下文隔离、嵌套追踪复位、日志写入故障、字段过滤、SQL 成功/失败统计、token 缺报与部分报告、模型超时、工具业务失败、向量和重排降级、幂等重放、缓存计划重试、取消以及真正 SSE 后台线程中的业务执行。统计脚本验证 Docker 前缀、重复日志、未结束请求、按请求筛选和空样本口径。

后端基础版本全量 397 项及 12 个子测试通过，前端 7 项通过。模型响应在测试边界模拟；SQL、业务处理器与 SSE 工作线程使用真实临时数据库验证。此阶段未重新执行真实模型、ASR 或线上部署。基础验证记录见本地忽略目录 `test-results/agent-observability-20261101/`。
