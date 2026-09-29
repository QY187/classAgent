# ClassAgent

ClassAgent 是一个面向学生的上课助手 Agent。核心体验是：课上录音，课后获得可回听的文字记录和有依据的智能纪要，再按课程持续整理、检索和复习。

当前仓库已进入技术验证阶段。功能范围、首版优先级、操作流程和待确认事项见 [产品初版报告](docs/product-brief-v0.3.md)；技术选型见 [技术栈方案](docs/technical-stack-plan-v0.1.md)。

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

当前前端页面：

- `/`：课程库，可创建课程并进入课程详情。
- `/courses/{courseId}`：课程详情，可创建课次并查看处理状态。
- `/lessons/{lessonId}`：课次详情，可浏览器录音、查看实时识别文字，也可单独上传音频保存。

当前 Compose 默认使用本地持久化卷保存音频，不依赖 MinIO 镜像；生产环境可以将 `STORAGE_BACKEND` 改为 `s3`，接入 S3 兼容对象存储。录音时由浏览器语音识别生成文字，结束后音频和已确认的文字片段一起保存。没有浏览器识别结果或仅上传已有音频时，只保存音频，不自动生成文字或纪要。

智能纪要仍使用 DeepSeek；如需生成纪要，在本地 `.env` 配置 `DEEPSEEK_API_KEY`，不要提交到 Git。
