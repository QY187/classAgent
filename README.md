# ClassAgent

ClassAgent 是一个面向学生的上课助手 Agent。核心体验是：课上录音，课后获得可回听的文字记录和有依据的智能纪要，再按课程持续整理、检索和复习。

当前仓库已进入技术验证阶段。功能范围、首版优先级、操作流程和待确认事项见 [产品初版报告](docs/product-brief-v0.3.md)；技术选型见 [技术栈方案](docs/technical-stack-plan-v0.1.md)。

## 建议的首版闭环

录音或导入音频 → 带时间戳和说话人的转写 → 生成智能纪要报告 → 点击纪要回到原文和音频 → 按课程管理与问答。

## 仓库约定（初版）

- `docs/`：产品、设计与技术方案。
- `apps/api/`：FastAPI 后端和异步 Worker。
- `apps/web/`：Next.js 前端技术验证页面。
- `docker-compose.yml`：PostgreSQL、Redis、API 和 Worker 的本地开发环境。

## 技术验证版启动

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

当前 Compose 默认使用本地持久化卷保存音频，不依赖 MinIO 镜像；生产环境可以将 `STORAGE_BACKEND` 改为 `s3`，接入 S3 兼容对象存储。默认使用 `TRANSCRIPTION_PROVIDER=mock`，上传音频后会生成一条模拟转写片段，用来验证上传、异步任务、状态和结果保存链路。真实 ASR 服务接入前，不应把模拟内容当作实际课堂转写结果。
