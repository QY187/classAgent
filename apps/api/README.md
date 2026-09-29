# ClassAgent API 技术验证版

## 本地启动

1. 复制配置：`Copy-Item .env.example .env`
2. 在仓库根目录启动依赖和 API：`docker compose up --build`
3. 打开 API 文档：<http://localhost:8000/docs>
4. 前端可在 `apps/web` 安装依赖后启动：`npm install; npm run dev`

Compose 默认使用本地持久化卷保存音频，避免本地开发依赖 MinIO 镜像；生产环境可将 `STORAGE_BACKEND` 改为 `s3` 并配置 S3 连接信息。

Worker 支持两种转写模式：`mock` 会生成模拟片段用于本地链路验证；`paraformer` 使用阿里云百炼官方 `dashscope` SDK 上传本地音频并调用 Paraformer 文件转写，解析时间戳、文本和说话人后写入 `transcript_segments`。配置 `DASHSCOPE_API_KEY`、`TRANSCRIPTION_PROVIDER=paraformer` 和 `ASR_MODEL=paraformer-v2` 后即可启用真实 ASR。

智能纪要使用 DeepSeek 兼容接口。Docker Compose 从仓库根目录的 `.env` 读取 `DEEPSEEK_API_KEY`，生成纪要时会将本节课的文字记录发送给 DeepSeek，并把结构化结果保存到 PostgreSQL。API Key 只放在本地 `.env`，不要提交到 Git。
