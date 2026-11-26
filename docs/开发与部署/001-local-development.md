# ClassAgent 本地开发启动说明

导航：[文档索引](../README.md) / 开发与部署 · 编号 001 · 编排日期 2026-09-29

本文用于在 Windows + Docker Desktop 环境启动当前开发版。

## 1. 环境要求

- Windows 10/11
- Docker Desktop，并确认 Linux 容器引擎已经启动
- Node.js 22（与当前生产前端构建镜像一致）
- npm
- Git（可选，用于拉取代码）

当前版本不要求本机单独安装 PostgreSQL、Redis 或 Python。后端依赖会在 Docker 镜像中安装，数据库和队列也由 Docker Compose 启动。

## 2. 获取代码

如果还没有代码：

```powershell
git clone https://github.com/QY187/classAgent.git
Set-Location classAgent
```

如果已经有本地仓库：

```powershell
Set-Location D:\Code\agentCode\classAgent
git pull
```

## 3. 配置并启动后端依赖和任务服务

在仓库根目录创建本地 `.env`，已有文件请保留并按需编辑，不覆盖生产配置。Compose 从根目录读取变量；`apps/api/.env.example` 列出后端变量示例，其中 localhost 数据库地址用于本机 Python 运行，Compose 中数据库和 Redis 地址由服务配置覆盖。

| 变量 | 用途 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 百炼文件转写、默认文本向量服务 |
| `DEEPSEEK_API_KEY` | 默认纪要及兼容默认配置的生成模型 |
| `AGENT_PROVIDER`、`AGENT_BASE_URL`、`AGENT_API_KEY`、`AGENT_MODEL`、`AGENT_MODELS` | Agent 默认模型与聊天可选模型目录，见 [多模型接入](../问答与Agent/014-agent-models.md) |
| `SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD` | 令牌密钥和空库首次管理员初始化；启动前自行设置，不把开发默认配置用于生产 |
| `MEMORY_CONTEXT_BUDGET` | 对话记忆估算预算，默认 16000，范围 512—24000 |
| `MEMORY_SUMMARY_ENABLED`、`MEMORY_SEMANTIC_ENABLED` | 摘要/压缩生成与语义召回开关，默认 true；关闭语义时仍可关键词召回 |

修改管理员环境变量不会重置数据库中已有账号的密码。模型凭据不是页面启动的前提；未配置时可以管理课程、资料和课表，模型相关调用会提示配置或服务错误。密钥只留在服务端本地配置，不加入 Git。

先启动 Docker Desktop，然后在仓库根目录执行：

```powershell
docker compose up --build -d
```

该命令会启动：

- PostgreSQL + pgvector：保存账号、课程、课次、学习记录、记忆和向量索引。
- Redis：保存 Celery 队列与任务结果，也用于令牌/会话控制。
- FastAPI（api）：提供鉴权与业务 API，并尝试投递异步任务。
- Celery Worker（worker）：消费队列，执行转写、纪要、资料索引及记忆后台任务。
- Celery Beat（beat）：每分钟投递转写/资料索引补偿，每十分钟投递回收站清理。

正常上传请求直接尝试投递到队列，不必等待 Beat。Beat 是定时任务生产者，Worker 才是消费者。默认后端均在 Docker 中运行，不需要在 IDEA 再启动一个 API；只有选择本机 Python 调试时才需自行配置解释器、依赖和连接地址。

首次构建下载 LibreOffice、中文字体及 OCR 依赖可能较慢。依赖不变时复用镜像；后端源码通过挂载更新，API 有热重载，但 Worker/Beat 需重启以加载新代码。

检查服务状态：

```powershell
docker compose ps
```

正常情况下，`postgres` 和 `redis` 显示 `healthy`，`api`、`worker` 和 `beat` 显示运行中。

检查 API：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

预期结果：

```text
status
------
ok
```

API 调试文档：<http://localhost:8000/docs>

## 4. 启动前端

第一次启动或依赖变化后，进入前端目录安装依赖：

```powershell
Set-Location apps/web
npm ci
```

启动开发服务器：

```powershell
npm run dev
```

打开：<http://localhost:3000>

如果 API 不在默认地址，可以设置：

```powershell
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev
```

## 5. 手动体验（按需执行）

1. 打开 <http://localhost:3000> 并登录；首页展示学习概览、本周课程表和课程入口。
2. 创建一门课程。
3. 进入课程，创建一节课次。
4. 打开课次详情。
5. 在支持浏览器语音识别的浏览器中点击“开始录音”，允许麦克风权限并说一段中文。
6. 点击“结束录音”，等待音频和已确认的浏览器识别文字保存。
7. 在“文字记录”区域查看识别结果。

也可以直接选择已有音频文件。配置 `DASHSCOPE_API_KEY` 后，后台会调用阿里云百炼 Paraformer 文件转写；浏览器录音没有产生已确认文字时同样会走该流程。转写完成后再生成智能纪要。

### 课程级问答

Agent 聊天输入区提供模型选择，按对话保存，刷新后恢复；默认兼容 DeepSeek，支持已配置的百炼及自定义兼容接口。管理员可以通过 `AGENT_MODELS` 注入更多选项，详见 [Agent 多模型接入](../问答与Agent/014-agent-models.md)。下述旧课程问答接口仍使用 DeepSeek。

课程详情页的“问一问”会检索本课程已整理的课堂内容，并把回答引用链接到文字记录和录音时间点。问答需要在根目录 `.env` 同时配置 `DASHSCOPE_API_KEY`（文本向量）和 `DEEPSEEK_API_KEY`（生成回答）。首次升级后，已有课次在课程详情页点击“整理或更新课程资料”建立索引；新课次的转写和纪要会自动触发索引。索引由 Worker 异步完成，提交后稍等并刷新页面查看片段数量。

### 复习卡片与知识点清单

课次的“智能纪要”页面可以进入“复习卡片”。点击“从纪要生成”会提取有原文来源的核心概念；也可以手动创建、编辑或删除卡片。左侧“知识点清单”汇总全部课程的卡片，课程搜索框默认显示全部课程；点开后下拉显示所有课程（包括还没有知识点的课程），输入名称时列表和知识点同步筛选，选中课程后只看该课程，清空后恢复全部；也可按“未学习”“需要复习”“已掌握”筛选。用户看过后手动修改状态，没有到期时间或自动复习安排。每张卡片标明所属课次，点击来源可跳到文字记录和录音时间点。数据库中原有的复习时间列暂留以兼容旧数据，但业务逻辑不再使用。

本地数据库使用带 pgvector 扩展的 PostgreSQL 16 镜像；首次升级执行 `docker compose up --build -d` 会下载新镜像并保留原有 `postgres_data` 数据卷。向量列固定为 1536 维，对应默认 `text-embedding-v2`；更换向量模型前需要迁移向量列并重建全部索引。

### 课表、记忆与课程 PDF

- `/timetable`：先设置学期，再上传 PDF/CSV/XLS；预览校对后确认导入。扫描课表使用本地 OCR，不需要模型密钥。大小、版式与并发限制见 [课程表与导入](../课程/004-timetable.md)。
- `/chat`、`/memories`：体验对话上下文、历史召回、明确保存的偏好和临时模式。压缩、摘要及向量调用按配置计量，不保证逐字记忆；见 [记忆机制](../问答与Agent/015-agent-memory.md)。
- `/courses/{courseId}/export`：四类资料默认全选，预览真实 PDF 后下载 ZIP；读取已保存资料，不调用模型。见 [课程导出](../课程/003-course-export.md)。

## 6. 查看日志

查看所有服务日志：

```powershell
docker compose logs -f
```

只看 API：

```powershell
docker compose logs -f api
```

只看 Worker 和 Beat：

```powershell
docker compose logs -f worker beat
```

按 `Ctrl+C` 退出日志查看，不会停止服务。

## 7. 停止和重新启动

停止容器但保留数据：

```powershell
docker compose down
```

下次启动：

```powershell
docker compose up -d
```

只修改后端源码并需要后台任务加载新代码时，先确认 Worker 的 active/reserved 为空，再重启后台服务：

```powershell
docker compose exec worker celery -A app.infrastructure.tasks.celery_app inspect active
docker compose exec worker celery -A app.infrastructure.tasks.celery_app inspect reserved
docker compose restart worker beat
```

如果修改了后端依赖或 Dockerfile（例如新增 OCR 库），需要重新构建三个后端服务：

```powershell
docker compose up --build -d api worker beat
```

停止前端开发服务器，在运行 `npm run dev` 的终端按 `Ctrl+C`。

## 8. 数据保留规则

开发 Compose 默认使用 `classagent` 作为项目名，在中文目录中也能启动。若此前使用其他项目名启动过，沿用原来的 `docker compose -p <项目名>` 命令可继续使用对应的数据卷。

当前数据保存在 Docker 持久化卷：

- `classagent_postgres_data`：数据库数据
- `classagent_audio_data`：上传的音频及附件文件

开发 Compose 未为 Redis 显式配置持久卷，重建后队列和任务结果可能丢失；数据库与上传文件使用上述卷。普通的 `docker compose down` 不会删除这些命名卷。不要在需要保留数据时执行：

```powershell
docker compose down -v
```

`down -v` 会删除 Compose 管理的卷，课程、课次和本地上传音频可能无法恢复。

## 9. 常见问题

### Docker 命令提示无法连接引擎

启动 Docker Desktop，等待状态变为运行中，再执行：

```powershell
docker compose up --build -d
```

### 页面提示无法连接后端

检查 API：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

如果失败，查看日志：

```powershell
docker compose logs --tail=100 api worker
```

### API 启动时提示 PostgreSQL 连接失败

查看状态：

```powershell
docker compose ps
```

等待 `postgres` 变为 `healthy` 后启动应用服务：

```powershell
docker compose up -d api worker beat
```

### 后台任务启动失败（Kombu / Redis 依赖不兼容）

若 Worker 或 Beat 日志出现 `ModuleNotFoundError: No module named 'packaging'`，或提示 Redis 传输要求更高版本的 redis-py，应检查间接依赖 Kombu 是否被自动升级。`apps/api/requirements.txt` 已固定 `kombu==5.4.2`，与现有 Celery 和 Redis 客户端一起使用；更新代码后重建本地镜像：

```powershell
docker compose up -d --build api worker beat
docker compose exec worker celery -A app.infrastructure.tasks.celery_app inspect ping
```

确认 API 能正常访问、Worker 返回 `pong`，且 Beat 不再重启。无需删除数据库或上传文件的数据卷。

### 端口被占用

当前默认端口：

- 前端：3000
- API：8000
- PostgreSQL：5432
- Redis：6379

查看端口占用：

```powershell
Get-NetTCPConnection -LocalPort 3000,8000,5432,6379 -State Listen
```

### 页面显示旧内容或出现开发构建异常

停止前端后，删除 Next.js 本地缓存再重新启动：

```powershell
Set-Location apps/web
Remove-Item -Recurse -Force .next
npm run dev
```

## 10. 当前版本边界

- 已有账号登录、多用户归属和回收站；管理员配置用于空库初始化，不是每次启动覆盖账号。
- 已有全局搜索、课程问答、课件解析与带来源小测。文字型课件与扫描课表属于不同解析入口，普通扫描课件暂不支持 OCR 问答。
- 录音尝试浏览器语音识别；没有已确认文字时走百炼文件转写，不生成模拟转写。
- 记忆预算是应用估算预算，不是模型上下文窗口；长期偏好需明确保存，历史召回不保证命中所有旧消息。
- 课程 PDF 预览与 ZIP 导出均读取已保存资料；纪要、题目与 OCR 结果仍需核对。
- 当前开发和生产均可使用本地文件卷，S3 是可选部署配置，不是启动的前提。
- 待办/疑问模块、学习时长统计与自动掌握程度推断仍未实现。当前范围见 [README](../../README.md)，线上版本与验收范围见 [部署记录](003-production-deployment.md)。
