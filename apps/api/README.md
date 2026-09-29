# ClassAgent API 技术验证版

## 本地启动

1. 复制配置：`Copy-Item .env.example .env`
2. 在仓库根目录启动依赖和 API：`docker compose up --build`
3. 打开 API 文档：<http://localhost:8000/docs>
4. 前端可在 `apps/web` 安装依赖后启动：`npm install; npm run dev`

Compose 默认使用本地持久化卷保存音频，避免本地开发依赖 MinIO 镜像；生产环境可将 `STORAGE_BACKEND` 改为 `s3` 并配置 S3 连接信息。

录音时由浏览器语音识别生成文字。上传接口会保存音频和浏览器已确认的文字片段，不调用音频转写服务，也不生成模拟转写。单独上传已有音频只保存文件；浏览器不支持语音识别或没有识别结果时，课次没有文字记录，无法生成智能纪要。

智能纪要使用 DeepSeek 兼容接口。Docker Compose 从仓库根目录的 `.env` 读取 `DEEPSEEK_API_KEY`，生成纪要时会将本节课的文字记录发送给 DeepSeek，并把结构化结果保存到 PostgreSQL。API Key 只放在本地 `.env`，不要提交到 Git。
