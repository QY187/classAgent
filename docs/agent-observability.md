# Agent 请求级追踪与指标统计

更新时间：2026-11-01。

## 1. 范围与入口

普通聊天接口和 SSE 聊天接口最终都调用 `send_message`，在这里建立请求追踪；该请求内的语义规划、模型协议适配、工具执行、RAG 检索、回答核验、数据库保存共享同一追踪上下文。SSE 在后台线程执行真正的业务请求，由该线程建立独立上下文，页面断开连接不提前宣告后台任务结束。

本次为本地实现，发布前线上仍使用上一版。没有新增依赖；为追踪持久化增加摘要/工具索引表和用户角色列，未改变业务工具授权、模型提示词正文、模型重试预算或检索参数。

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

## 6. 运行监控页面与持久化

管理员登录后，左侧导航提供「运行监控」，地址为 `/monitoring`。页面包含：

- 最近 1 小时、24 小时、7 天和 30 天的请求尝试、正常返回率、耗时 P50/P95、已报告 Token。
- 按状态、实际执行工具和完整 `request_id` 筛选；默认每页 20 条，按开始时间倒序分页。
- 请求详情中的父子执行阶段、模型与工具信息、错误类型、修复与降级原因码、SQL 次数及 Token 缺报情况。
- 普通用户在自己的聊天回答（或失败的问题）下展开「查看请求执行详情」，只能读取本人、当前对话的追踪；最多查看最近 20 次尝试。管理员从聊天入口也受本人范围限制。

统计单位是一次 `trace_id` 尝试，不是去重后的问题数。正常返回率为 `status=ok / 已结束尝试`，分母包括异常和取消；它不等于回答正确率或任务完成率。`outcome` 单独显示业务结果。Token、模型和工具计数仅汇总已结束请求；P50/P95 仅使用已结束且有耗时的请求，使用 nearest-rank。空样本显示 `—`。页面所有筛选同时作用于请求列表和概览；翻页保留同一截止时间，点击刷新才更新统计窗口。

API：

| 接口 | 权限与用途 |
| --- | --- |
| `GET /monitoring/overview` | 管理员；筛选范围内的计数与耗时分位数 |
| `GET /monitoring/traces` | 管理员；分页摘要，不携带事件正文 |
| `GET /monitoring/tools` | 管理员；指定时间范围出现的执行工具名 |
| `GET /monitoring/traces/{trace_id}` | 管理员；一次尝试的脱敏执行详情 |
| `GET /monitoring/requests/{request_id}?conversation_id=...` | 当前用户；仅返回本人记录，可进一步限定当前对话 |

查询时间必须有时区，采用 `[since, until)`，单次最多 31 天。管理员权限取自数据库中的 `users.role`，不信任前端本地存储、请求参数或仅凭用户名判断。未登录返回 401，普通用户访问管理接口返回 403，读取不到本人追踪返回 404。

启动时幂等创建 `agent_traces` 和 `agent_trace_tools` 表，并为旧 `users` 表增加默认 `user` 的角色列。新库的初始化管理员明确写入 `admin`。旧库首次加列时，仅当启动管理员用户名及密码均与已有账号匹配，才授予该账号管理员角色；不会在每次启动时根据用户名反复提升权限。若旧管理员已修改密码、与初始化配置不一致，需要运维核对实际用户 ID 后在数据库授予角色；不要重置其密码或开放自助提升权限。

持久化流程：

1. 请求开始以独立事务写入 `running` 摘要，以便管理员发现未结束尝试。
2. 业务执行过程中，在当前 trace 的有界内存缓冲中保留结束阶段与原因事件，不保存每个 `span.started`。
3. 请求正常结束、可捕获异常或取消时，用另一个独立事务更新汇总、已验证的用户归属及阶段事件。
4. 每条 trace 最多保留 512 条普通事件，并始终保留最终汇总；超限展示省略数，汇总计数和工具筛选索引不受事件截断影响。

存储使用独立的小连接池及 PostgreSQL 的连接、语句和锁等待超时；写入故障不回滚业务事务、不改变业务返回值、不计入业务 SQL 指标，但同步落库可能增加少量请求延迟。未引入无限队列或每阶段逐条写库。故障仅记录固定 `trace_persistence_failed`，不包含数据库地址或异常文本。若开始写入失败而结束写入成功，仍会补建完整记录；两次均失败则看板中没有这条记录，需要结合容器日志排查。

阶段详情在请求结束时落库，运行中只展示开始摘要，不提供实时阶段流。超过 30 分钟仍无结束记录标记「长时间未结束」，不自动判定业务失败。进程被强杀可能只有开始记录且没有用户归属，普通用户无法读取这种记录，管理员仍能看到。监控页不回填启用持久化前的历史日志。

数据保留目前由运维管理，未添加自动删除任务。数据库记录含用户与资料的后端标识，需纳入数据库访问控制和备份策略。按时间清理时应在同一事务中先删对应 `agent_trace_tools`，再删 `agent_traces`，或利用 PostgreSQL 外键级联；不要删除业务对话或课程。生产使用前应按实际审计需求制定保留期限。

## 7. 安全与未覆盖项

追踪只允许明确列出的指标字段；不写入提问、回答、课程/课次名称、工具参数与结果、SQL/参数、供应商错误文本、密钥或思考内容。不支持的工具名使用 `unknown` 代替，异常标识字符串规范化为 `invalid`。日志包含用户、对话和资料的后端标识，应沿用服务器运维日志访问控制，日志保留与轮转由部署环境配置。

当前已提供上述受限的脱敏追踪查询 API、监控页面和数据库存储，尚未接入集中式 Trace 平台或自动告警。范围从业务 `send_message` 开始，不覆盖之前的鉴权/HTTP 建连，也不包括独立 RAG 接口和 Celery 后台转写跨进程追踪；单独调用工具或检索时，只有处于活动请求追踪中才输出阶段日志。本次不为补充观测改变原有业务事务、工具权限和执行顺序。

## 8. 本次验证

2026-11-01：新增 16 项专项测试通过，覆盖父子阶段、线程和异步上下文隔离、嵌套追踪复位、日志写入故障、字段过滤、SQL 成功/失败统计、token 缺报与部分报告、模型超时、工具业务失败、向量和重排降级、幂等重放、缓存计划重试、取消以及真正 SSE 后台线程中的业务执行。统计脚本验证 Docker 前缀、重复日志、未结束请求、按请求筛选和空样本口径。

加入监控功能后，新增 22 项后端测试通过，覆盖真实存储与独立 Session、运行中与长时间未结束、401/403/404、不同用户使用同一请求编号、同一用户跨对话、重试记录、正常返回率分母、Token 部分缺报、nearest-rank、分页与筛选、无效参数、持久化故障、事件截断、角色读取/注册、存量角色迁移和真正消息入口的幂等重放。

最终后端全量 419 项及 12 个子测试通过；前端 10 项通过，额外验证阶段树父先子后、截断/循环引用和未知耗时/用量覆盖口径。生产构建及 TypeScript 检查通过。

本地浏览器 7 项检查通过：管理导航与初始页、真实模型请求与 PostgreSQL 落库、请求筛选及阶段详情、工具筛选和空结果恢复、390px 移动端无整页横向溢出、普通用户无法访问管理页/他人记录、聊天消息展示本人追踪。未检测到浏览器页面异常。测试使用临时账号及对话，结束后清理其账号、对话、追踪和工具索引，不在监控页保留演示数据。桌面与移动端截图已检查。

后端自动化用模拟供应商响应核对错误与缺报边界；浏览器真实模型请求仅证明本地追踪链路连通，不构成 RAG 回答质量评测、生产性能基准或线上验收。本轮未部署线上、未计算真实费用。完整记录见本地忽略目录 `test-results/monitoring-20261101/`，基础追踪验证历史在 `test-results/agent-observability-20261101/`。
