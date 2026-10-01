# ClassAgent

ClassAgent 是一个面向学生的上课助手 Agent。核心体验是：课上录音，课后获得可回听的文字记录和有依据的智能纪要，再按课程持续整理、检索和复习。

当前仓库已进入技术验证阶段。功能范围、首版优先级、操作流程和待确认事项见 [产品初版报告](docs/product-brief-v0.3.md)；技术选型见 [技术栈方案](docs/technical-stack-plan-v0.1.md)；后续复习和资料管理模块见 [后续功能规划](docs/feature-roadmap-v0.1.md)。

## 建议的首版闭环

录音或导入音频 → 带时间戳和说话人的转写 → 生成智能纪要报告 → 点击纪要回到原文和音频 → 按课程管理与问答。

## 仓库约定（初版）

- `docs/`：产品、设计与技术方案。
- `apps/api/`：FastAPI 后端和异步 Worker。
- `apps/web/`：Next.js 前端页面框架，包含课程库、课程详情和课次详情。
- `docker-compose.yml`：PostgreSQL、Redis、API 和 Worker 的本地开发环境。
- `docs/local-development.md`：本地启动、验证、停止和故障排查说明。

## 技术验证版启动

完整步骤见 [本地开发启动说明](docs/local-development.md)。

需要先启动 Docker Desktop，然后在仓库根目录执行：

```powershell
docker compose up --build
```

API 文档地址：<http://localhost:8000/docs>。

另开一个终端启动前端：

```powershell
Set-Location apps/web
npm install
npm run dev
```

前端地址：<http://localhost:3000>。

当前前端页面和能力：

- `/`：课程库，可创建课程并进入课程详情。
- `/courses/{courseId}`：课程详情，可创建课次并查看处理状态。
- `/lessons/{lessonId}`：课次工作台，可浏览器录音、查看实时识别文字，也可上传已有音频异步转写；处理完成后可进入智能纪要和文字记录。
- `/lessons/{lessonId}/transcript`：查看带时间戳的文字记录，支持编辑、合并片段、重命名说话人、播放定位和下载。
- `/lessons/{lessonId}/summary`：查看、生成、编辑和重新生成智能纪要，并回到文字记录核对来源。
- `/courses/{courseId}`：课程详情中的“问一问”可跨课次提问，查看带课次、原文片段和时间点的引用；已有课次可手动补建问答索引。

当前已完成的核心闭环是：录音或导入音频 → 带时间戳和说话人的转写 → 智能纪要 → 原文和音频回溯 → 课程级问答和引用。下一阶段计划开发今日复习、复习卡片、待办与疑问、测验、资料库、全局搜索和学习进度，详见 [后续功能规划](docs/feature-roadmap-v0.1.md)。

当前 Compose 默认使用本地持久化卷保存音频，不依赖 MinIO 镜像；生产环境可以将 `STORAGE_BACKEND` 改为 `s3`，接入 S3 兼容对象存储。录音时由浏览器语音识别生成文字，结束后音频和已确认的文字片段一起保存。直接上传已有音频，或浏览器录音没有识别结果时，后台会调用阿里云百炼 Paraformer 文件转写并保存带时间戳的文字片段。

智能纪要仍使用 DeepSeek；如需生成纪要，在本地 `.env` 配置 `DEEPSEEK_API_KEY`，不要提交到 Git。

上传文件转写需要在本地 `.env` 配置 `DASHSCOPE_API_KEY`。可用 `ASR_MODEL` 和 `DASHSCOPE_BASE_URL` 指定模型与百炼地域端点。开发环境使用百炼临时文件存储取得转写 URL；生产环境应改用稳定可访问的 OSS 地址。
