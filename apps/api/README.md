# ClassAgent API 技术验证版

## 本地启动

1. 复制配置：`Copy-Item .env.example .env`
2. 在仓库根目录启动依赖和 API：`docker compose up --build`
3. 打开 API 文档：<http://localhost:8000/docs>
4. 前端可在 `apps/web` 安装依赖后启动：`npm install; npm run dev`

Compose 默认使用本地持久化卷保存音频，避免本地开发依赖 MinIO 镜像；生产环境可将 `STORAGE_BACKEND` 改为 `s3` 并配置 S3 连接信息。

当前 `TRANSCRIPTION_PROVIDER=mock`，Worker 会生成一条模拟转写片段，用于验证上传、队列、状态和结果保存链路。接入真实服务时，在 `app/tasks.py` 中实现对应的 ASR 适配器。

智能纪要使用 DeepSeek 兼容接口。Docker Compose 从仓库根目录的 `.env` 读取 `DEEPSEEK_API_KEY`，生成纪要时会将本节课的文字记录发送给 DeepSeek，并把结构化结果保存到 PostgreSQL。API Key 只放在本地 `.env`，不要提交到 Git。
