# ClassAgent API 技术验证版

## 本地启动

1. 复制配置：`Copy-Item .env.example .env`
2. 在仓库根目录启动依赖和 API：`docker compose up --build`
3. 打开 API 文档：<http://localhost:8000/docs>
4. 前端可在 `apps/web` 安装依赖后启动：`npm install; npm run dev`

Compose 默认使用本地持久化卷保存音频，避免本地开发依赖 MinIO 镜像；生产环境可将 `STORAGE_BACKEND` 改为 `s3` 并配置 S3 连接信息。

录音时由浏览器语音识别生成文字。上传接口会保存音频和浏览器已确认的文字片段；直接上传已有音频，或浏览器没有识别结果时，会创建后台任务，使用阿里云百炼 Paraformer 转写音频。配置 `DASHSCOPE_API_KEY` 后即可使用上传转写；可通过 `ASR_MODEL`、`DASHSCOPE_BASE_URL` 调整模型与地域端点。开发环境使用百炼临时文件存储，生产环境应改用稳定可访问的 OSS 地址。

智能纪要使用 DeepSeek 兼容接口。Docker Compose 从仓库根目录的 `.env` 读取 `DEEPSEEK_API_KEY`，生成纪要时会将本节课的文字记录发送给 DeepSeek，并把结构化结果保存到 PostgreSQL。API Key 只放在本地 `.env`，不要提交到 Git。
