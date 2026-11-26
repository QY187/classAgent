# ClassAgent

ClassAgent 是面向学生的课堂学习助手：按课程和课次保存录音、文字记录、纪要和课件，结合有来源的问答、知识点、小测与课程表，支持课后回顾和复习。

当前已提供可运行的 Web 应用，正式入口为 [njust.shop](https://njust.shop)。截至 2026-11-25，问答记忆、课程表与课表 OCR 等更新已部署；本次按用户要求只做启动、健康和运行状态检查，未做线上业务验收。具体版本、验证范围与回退信息见 [生产部署记录](docs/production-deployment.md)。

## 已实现的能力

- **课堂资料**：浏览器录音或上传音频，保存带时间戳的转写；编辑文字、合并片段、重命名说话人，按片段定位音频，并收藏或标记没听懂的片段。
- **纪要与复习**：生成、编辑智能纪要，追溯原文；管理知识点和掌握状态，生成有来源的单选/判断小测，查看成绩、错题及课程学习进度。
- **课件与搜索**：上传、预览、下载、替换课件；文字型 PDF、PPTX、DOCX、TXT、Markdown 可解析、索引并参与问答和出题。全局搜索支持输入自动搜索、中文简写、多关键词和来源定位。
- **问答与记忆**：主对话跨本人可见课程，课程对话限定当前课程；支持流式回答、工具执行记录、引用核对、模型选择、归档和失败说明。按预算压缩较早对话，结合历史召回和明确保存的长期记忆，提供管理页、开关与临时模式。
- **课程表**：管理学期、节次和排课，首页显示本周及今日课程；支持周次直达、重叠卡片，以及 PDF（含扫描件）、CSV、旧版 XLS 的预览校对与确认导入。
- **PDF 导出**：整门课程或指定课次，将智能纪要、知识点、小测题目、文字记录统一打包为 PDF ZIP；四项默认全选，下载前可查看真实 PDF、翻页和缩放。
- **账号与运维**：登录和用户数据隔离、头像及密码设置、回收站、每日模型 Token 额度、管理员额度管理与运行监控。

课表扫描件 OCR 仅用于课表导入，不代表普通扫描课件也能 OCR 问答；后者及图表理解仍有边界。长期记忆不保证逐字记住所有历史，也不能代替课堂原文或新的操作授权。

## 本地快速启动

需要 Docker Desktop（Linux 引擎）、Node.js 22 和 npm。默认由 Docker 运行后端与依赖，前端由本机 Node.js 启动；不需要从 IDEA 单独运行后端，也不要求本机安装 Python、PostgreSQL 或 Redis。

在仓库根目录按需建立本地 `.env`，配置服务端模型凭据及管理员配置，详见 [本地开发说明](docs/local-development.md)。未配置模型凭据也可启动页面、管理资料、预览导出和使用本地课表 OCR；转写、生成与向量调用需要各自有效配置。

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
```

另开终端：

```powershell
Set-Location apps/web
npm ci
npm run dev
```

打开 [本地前端](http://localhost:3000)；后端接口说明位于 [API Docs](http://localhost:8000/docs)。首次构建包含 LibreOffice、中文字体和 OCR 依赖，下载较大；后续依赖不变时复用镜像和缓存。修改后端依赖后需重建 `api`、`worker`、`beat`，仅重新启动旧镜像不能安装新增依赖。

| 服务 | 职责 |
| --- | --- |
| PostgreSQL + pgvector | 保存账号、课程、学习记录、记忆与向量索引 |
| Redis | Celery 消息队列及任务结果；也用于令牌与会话控制，不只是缓存 |
| API | 鉴权、业务接口、资料读写及任务投递 |
| Worker | 消费队列，执行转写、纪要、资料索引和记忆后台任务 |
| Beat | 定时投递转写补偿、索引补偿和回收站清理任务；不负责从 Redis 取任务交给 Worker |
| 本机 Next.js | 提供开发前端；生产环境前端也运行于 Docker |

正常任务在业务请求中直接尝试投递，Beat 用于定时补偿和清理，不是上传后必须等待的正常入口。服务日志、配置、停止与数据保留方法见 [本地开发说明](docs/local-development.md)。

## 页面入口

| 页面 | 用途 |
| --- | --- |
| `/`、`/timetable` | 学习概览、本周课表与完整课表管理 |
| `/courses/{courseId}`、`/lessons/{lessonId}` | 课程资料与课次录音工作台 |
| `/lessons/{lessonId}/transcript`、`/lessons/{lessonId}/summary` | 文字记录、书签、智能纪要与来源回溯 |
| `/courses/{courseId}/materials/{materialId}` | 课件提取原文及来源定位 |
| `/chat`、`/memories` | 问答工作台与记忆管理 |
| `/search`、`/review` | 全局搜索与知识点清单 |
| `/courses/{courseId}/quizzes`、`/wrong-questions` | 小测与错题本 |
| `/courses/{courseId}/progress`、`/pending-lessons` | 学习统计与待处理课次 |
| `/courses/{courseId}/export` | 课程 PDF 预览及 ZIP 导出 |
| `/settings`、`/recycle-bin`、`/quotas`、`/monitoring` | 个人设置、回收站、额度与运行监控（按权限展示） |

## 配置与能力边界

- 浏览器通过 MediaRecorder 录音，并尝试浏览器语音识别；浏览器识别可用性取决于浏览器、权限与网络。直接上传音频，或录音未获得已确认文字时，后台使用百炼文件转写，需要 `DASHSCOPE_API_KEY`。
- 默认纪要使用 DeepSeek，需要 `DEEPSEEK_API_KEY`。Agent 可通过 `AGENT_*` 与 `AGENT_MODELS` 配置兼容模型，聊天只选择服务端允许的模型编号；详见 [多模型说明](docs/agent-models.md)。
- 文本向量默认使用百炼 `text-embedding-v2`，向量列固定 1536 维。改变模型或维度前需规划迁移；不要直接切换配置后沿用旧索引。
- 记忆默认预算 `MEMORY_CONTEXT_BUDGET=16000` 是应用估算预算，约在可用预算的 80% 触发压缩，不是模型完整上下文窗口。详见 [记忆机制](docs/agent-memory.md)。
- 开发 Compose 默认将音频及附件保存于持久卷，不依赖 MinIO；生产当前也使用本地持久卷，可按需配置 S3 兼容存储。不要用本地 `.env` 覆盖生产配置。
- 来源缺失、资料不足与执行失败分别提示；模型生成的纪要、答案和题目仍应核对。课表 OCR 必须校对后导入。待办与疑问模块、学习时长统计、自动掌握程度推断尚未实现。

## 文档导航

| 内容 | 文档 |
| --- | --- |
| 启动、配置、日志、数据保留 | [本地开发](docs/local-development.md) |
| 发布、当前基线与回退 | [生产部署](docs/production-deployment.md) |
| 学期、排课、文件导入及 OCR 限制 | [课程表与导入](docs/timetable.md) |
| 范围、Agent、模型与记忆 | [主对话](docs/global-chat.md)、[课程 Agent](docs/course-agent.md)、[记忆机制](docs/agent-memory.md)、[模型配置](docs/agent-models.md) |
| 课件、出题与错题 | [课件问答](docs/material-question-answering.md)、[小测设置](docs/quiz-generation-settings.md)、[错题练习](docs/wrong-question-practice.md) |
| 导出、额度与统计 | [课程 PDF](docs/course-export.md)、[Token 额度](docs/token-quotas.md)、[首页统计](docs/home-overview.md) |
| 产品方向与剩余计划 | [产品初版报告](docs/product-brief-v0.3.md)、[后续规划](docs/feature-roadmap-v0.1.md) |

早期产品报告、技术栈方案及带日期的验证记录保留历史背景，不能将其中“待实现”“未部署”等当时状态作为当前运行说明。仓库结构为 `apps/web/`（Next.js）、`apps/api/`（FastAPI/Celery）、`docs/`（说明与方案）；开发与生产分别使用 `docker-compose.yml` 和 `docker-compose.prod.yml`，生产还需指定发布覆盖文件。
