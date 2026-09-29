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
- `/lessons/{lessonId}`：课次详情，可上传音频并查看异步转写结果。

当前 Compose 默认使用本地持久化卷保存音频，不依赖 MinIO 镜像；生产环境可以将 `STORAGE_BACKEND` 改为 `s3`，接入 S3 兼容对象存储。配置 `TRANSCRIPTION_PROVIDER=paraformer` 后，Worker 会通过阿里云百炼官方 `dashscope` SDK 将音频上传到临时 OSS，并调用 Paraformer 文件转写，保存带时间戳和说话人的片段。`mock` 仍可用于没有 ASR Key 时验证上传和队列链路。

真实 ASR 配置：

```env
DASHSCOPE_API_KEY=你的阿里云百炼 Key
TRANSCRIPTION_PROVIDER=paraformer
ASR_MODEL=paraformer-v2
```

Key 只放在本地 `.env`，不要提交到 Git。上传到百炼的临时音频由官方接口处理，Worker 不会把 Key 暴露给浏览器。
