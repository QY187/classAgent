# ClassAgent API 技术验证版

## 本地启动

1. 复制配置：`Copy-Item .env.example .env`
2. 在仓库根目录启动依赖和 API：`docker compose up --build`
3. 打开 API 文档：<http://localhost:8000/docs>
4. 前端可在 `apps/web` 安装依赖后启动：`npm install; npm run dev`

当前 `TRANSCRIPTION_PROVIDER=mock`，Worker 会生成一条模拟转写片段，用于验证上传、队列、状态和结果保存链路。接入真实服务时，在 `app/tasks.py` 中实现对应的 ASR 适配器。

