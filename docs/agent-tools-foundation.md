# Agent 工具基础

## 当前完成范围

实现 `apps/api/app/modules/agent/` 的工具注册、执行器和后端模型调用循环。复用已有业务服务，不新增数据表、公开接口或页面，也没有改变现有问答的执行路径。聊天执行进度与任务持久化尚未接入。

这一阶段只提供读取工具，不包含生成、删除、覆盖、账户修改或复习到期安排。后续按照用户已经确认的需求逐步接入纪要、知识点和小测。

## 模块边界

- `schemas.py`：严格参数类型、长度与分页上限，拒绝未知字段。
- `tools.py`：调用现有课程、课次、文字记录、纪要和搜索业务，转换为带来源的结果。
- `registry.py`：工具白名单与模型可读取的函数定义，注册表不可修改。
- `executor.py`：统一参数解析、身份与会话范围校验、结果和错误格式。

## 工具

| 名称 | 参数 | 返回内容 |
| --- | --- | --- |
| `list_courses` | 可选名称关键词、offset、limit | 用户可见课程，受当前课程范围约束 |
| `list_lessons` | course_id、可选标题关键词、offset、limit | 按当前手动排序返回课次，受当前课次范围约束 |
| `get_transcript` | lesson_id、offset、limit | 原文片段、片段 ID、说话人、起止时间、下一页位置 |
| `get_summary` | lesson_id、字符 offset、limit | 已有纪要的状态、可用性、内容分页 |
| `search_course` | course_id、query、可选 lesson_id、limit | 关键词命中的课堂文字片段、课次、时间点 |

列表默认 20 条，最多 50 条。文字记录每段最多返回 2000 字，超长段明确标记 `truncated`，不可把截短内容当作完整原文。纪要默认返回 8000 字，最多 12000 字，可按 `next_offset` 继续读取；排队、失败或过期内容不作为可用纪要返回。搜索最多返回 30 条；课次范围在数据库查询截断前应用，避免其他课次挤掉目标结果。

搜索复用现有全局搜索中的关键词查询，明确返回 `retrieval_method=keyword`。这一阶段不是语义检索，也不调用问答模型；未命中不代表课堂没有相关内容。后续编排层仍需处理来源校验与引用展示。

## 后端调用约定

```python
from app.modules.agent.executor import execute_tool
from app.modules.agent.registry import tool_schemas
from app.modules.agent.tools import ToolContext

# username 来自登录鉴权；course_id、lesson_id 来自已校验的对话。
context = ToolContext(username=username, course_id=conversation.course_id,
                      lesson_id=conversation.lesson_id)
definitions = tool_schemas()
result = execute_tool(db, context, "get_transcript", {"lesson_id": lesson_id, "limit": 10})
```

`ToolContext` 只能由后端创建，不属于模型参数。绑定课次时必须同时绑定所属课程。每次执行重新检查身份、归属、当前范围和回收站可见性；未知工具不能执行，模型不能传 SQL、Shell、用户身份或任意文件操作。

成功返回 `tool`、`ok=true`、`data` 和 `content_trust=untrusted_classroom_data`。后续模型循环必须明确把结果当作资料，不能执行课堂文本中的指令。

失败返回 `ok=false` 与结构化错误码：`unknown_tool`、`invalid_context`、`invalid_arguments`、`unauthenticated`、`not_found`、`unavailable` 或 `execution_failed`。不返回异常堆栈、凭据或原始无效参数。编排层需按结果决定修正参数、停止或重试；这一阶段没有实现自动重试或任务恢复。

## 验证

`apps/api/tests/test_agent_tools.py` 的 8 项测试覆盖注册定义、严格校验、课程课次顺序及分页、用户与对话范围隔离、原文引用及截短提示、纪要状态与分页、搜索课次过滤、回收站可见性和内部异常信息隐藏。

## 模型调用循环

`loop.run_agent(db, context, question, history=None, on_step=None, on_check=None)` 使用现有 DeepSeek 配置，通过 [官方 Tool Calls 协议](https://api-docs.deepseek.com/guides/tool_calls/) 提交函数定义、执行模型选择的工具并回传对应 `tool_call_id` 的结果。`completion.py` 负责非流式模型请求，沿用配置中的模型名，显式关闭思考模式；内部思考、密钥与供应商异常不返回给调用方。

- 最多 6 轮模型请求、8 次工具调用；每次模型请求设定网络超时，轮次与工具执行前后检查 90 秒期限。同步网络请求和数据库读取只能在返回后检查总期限，尚不具备强制中断能力。
- 通过 `on_check` 向上传播取消异常，模型请求进行中暂不能立即停止；`on_step` 返回工具开始、完成或失败状态，为后续页面接入预留。
- 参数错误或未知工具以结构化结果返回给模型，可修正后继续；整批工具协议先校验，不执行无效响应中的半批工具。到达调用上限直接停止，不无限重试。
- 单次工具结果超过 64000 字符时要求缩小分页；会话上下文超过 160000 字符时停止，历史仅保留最近 8 条、每条最多 1000 字。
- 仅本次实际读取或搜索到的原文可生成 `evidence_id`。纪要用于主题定位，生成课堂结论前仍需读取原文；历史回答和历史引用不作为事实依据。
- 回答前再次检查原文内容与权限，已修改、已删除或已失去权限的来源不返回引用。引用存在不保证 AI 对原文的理解完全正确，仍需回到课堂原文核对。
- 最终返回 `answer`、`citations`、`outcome` 与临时 `steps`；信息不足可返回 `needs_input`，没有有效原文依据返回 `insufficient_evidence`。执行器不保存任务或对话，也不新增资料。

`test_agent_loop.py` 的 9 项模拟模型测试覆盖多步工具结果回传、参数修正、来源校验与历史隔离、澄清及格式异常、调用预算、协议错误、期限与取消、原文变更/删除、模型协议与错误信息隐藏。该阶段尚未通过真实模型或前端联调验收。
