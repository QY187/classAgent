# Agent 多模型接入

更新时间：2026-11-04。

## 范围

Agent 的语义规划、工具选择、回答综合和一致性检查统一经过 `agent/completion.py`，现在可以独立选择供应商和模型。不配置新增变量时，继续使用 DeepSeek，沿用 `DEEPSEEK_API_KEY` 与 `SUMMARY_MODEL`。

当前通过服务端环境变量配置 Agent 模型，同一实例使用同一配置。

纪要、课堂出题和旧课程 RAG 接口仍使用原 DeepSeek 配置；Agent 调用这些工具时，工具内部的模型也沿用原配置。转写、向量化和重排配置不变，不提供失败自动切换。

## 配置

| 变量 | 用途 |
| --- | --- |
| `AGENT_PROVIDER` | `deepseek`（默认）、`dashscope` 或 `openai_compatible` |
| `AGENT_MODEL` | Agent 专用模型名；留空时 DeepSeek 沿用 `SUMMARY_MODEL`，百炼使用 `qwen-plus`；通用接口必须指定 |
| `AGENT_API_KEY` | Agent 专用密钥；留空时 DeepSeek 沿用 `DEEPSEEK_API_KEY`，百炼沿用 `DASHSCOPE_API_KEY`；通用接口必须指定 |
| `AGENT_BASE_URL` | 可选接口根地址；通用接口必须指定。可填以 `/chat/completions` 结尾的完整地址 |

密钥只放服务端环境变量，不使用 `NEXT_PUBLIC_`，不提交真实 `.env`。接口地址不能包含用户名、密码、查询参数或片段；需要鉴权时使用 `AGENT_API_KEY`。配置只从服务端读取，模型与客户端不能改变地址或密钥。

### 保持原 DeepSeek

```dotenv
AGENT_PROVIDER=deepseek
AGENT_BASE_URL=
AGENT_API_KEY=
AGENT_MODEL=
```

默认请求地址为 `https://api.deepseek.com/chat/completions`。如需 Agent 使用独立模型或密钥，填写 `AGENT_MODEL`、`AGENT_API_KEY`，不会改变纪要和出题的 `SUMMARY_MODEL`。

### 阿里云百炼

```dotenv
AGENT_PROVIDER=dashscope
AGENT_MODEL=qwen-plus
AGENT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AGENT_API_KEY=
```

留空的 `AGENT_API_KEY` 使用现有 `DASHSCOPE_API_KEY`。此默认地址对应北京地域；其他地域需要填写匹配的地址与密钥。应选择支持非流式 Chat Completions 和工具调用的模型。百炼请求显式发送 `enable_thinking=false`，DeepSeek 请求使用 `thinking.type=disabled`，避免供应商扩展字段互相串用。

### 其他兼容接口

```dotenv
AGENT_PROVIDER=openai_compatible
AGENT_BASE_URL=https://your-model-service.example/v1
AGENT_API_KEY=replace-with-server-side-key
AGENT_MODEL=your-tool-capable-model
```

通用接口必须完整填写地址、密钥和模型，不会回退使用其他供应商密钥。请求使用标准 `messages`、`tools`、`tool_choice=auto`、`temperature=0`、`max_tokens=2500`；纯文本阶段不发送 `tools` 或 `tool_choice`，不发送任何供应商专有思考参数。服务必须兼容这些参数，并返回标准 `choices[].message`、`finish_reason`、工具调用 ID 和函数参数。仅支持原生其他协议、要求额外专有参数或不支持工具调用的模型，仍需新增适配，不能保证只填地址就可用。

## 启用与回退

本地 Docker Compose：修改根目录 `.env`，执行 `docker compose up -d api worker` 重新创建容器使环境变量生效。Python 直接运行：配置进程环境或工作目录的 `.env` 后重启 API。设置有进程级缓存，仅热更新代码不会刷新配置。

生产环境通过 `.env.production` 注入变量，需要按 `production-deployment.md` 更新受影响服务；本功能没有自动修改生产环境、部署或切换当前模型。首次发布包含代码变化，不能仅重启旧镜像。

恢复原默认配置时将 `AGENT_PROVIDER=deepseek`，清空 `AGENT_BASE_URL`、`AGENT_API_KEY`、`AGENT_MODEL`，重建或重启相应服务。


## 额度、追踪与扩展

- 所有供应商经过原 `quota_chat_post`，沿用用户归属、调用前额度预留、实际 Token 结算和用量缺失时的保守处理。账本记录实际请求模型名，不重置额度。
- 供应商用量应返回 `usage.prompt_tokens`、`completion_tokens`、`total_tokens`。缺失用量不会被当作零消耗，也不会释放不确定预留。
- 模型追踪记录实际 `provider` 与 `model`，不记录密钥、接口地址、思考内容或供应商错误原文。
- 权限、引用校验、工具轮次、调用预算和取消逻辑不变。模型返回错误时按既有分类报错，不自动改用其他供应商重试。
- 新供应商兼容标准协议时使用通用配置；需要专有参数时，在 `providers.py` 增加供应商默认配置和请求适配，并补充对应测试。不把供应商分支散落到 Agent 业务流程。

## 验证

`tests/test_agent_model_providers.py` 覆盖三类供应商协议、旧配置兼容、独立覆盖、缺失配置、地址检查、环境变量、公开错误、响应格式以及真实 SQLite 工具读取与引用的完整循环。`tests/test_token_quotas.py` 验证多供应商仍经过真实额度账本。测试只模拟供应商网络边界，不证明每个第三方模型的实际回答质量，正式切换前需用目标模型验证真实课程问答与工具调用。

本提交测试模拟供应商网络边界，未调用新供应商付费接口，未部署或修改生产配置。

协议参考：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion)、[百炼 OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[百炼 Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)。
