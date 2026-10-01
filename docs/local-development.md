# ClassAgent 本地开发启动说明

本文用于在 Windows + Docker Desktop 环境启动当前技术验证版。

## 1. 环境要求

- Windows 10/11
- Docker Desktop，并确认 Linux 容器引擎已经启动
- Node.js 20 或更高版本
- npm
- Git（可选，用于拉取代码）

当前版本不要求本机单独安装 PostgreSQL、Redis 或 Python。后端依赖会在 Docker 镜像中安装，数据库和队列也由 Docker Compose 启动。

## 2. 获取代码

如果还没有代码：

```powershell
git clone https://github.com/QY187/classAgent.git
Set-Location classAgent
```

如果已经有本地仓库：

```powershell
Set-Location D:\Code\agentCode\classAgent
git pull
```

## 3. 启动后端依赖和任务服务

先启动 Docker Desktop，然后在仓库根目录执行：

```powershell
docker compose up --build -d
```

该命令会启动：

- PostgreSQL：保存课程、课次、任务和转写数据
- Redis：保存异步任务队列
- FastAPI：提供后端 API
- Celery Worker：执行音频处理和转写任务

检查服务状态：

```powershell
docker compose ps
```

正常情况下，`postgres` 和 `redis` 显示 `healthy`，`api` 和 `worker` 显示 `Up`。

检查 API：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

预期结果：

```text
status
------
ok
```

API 调试文档：<http://localhost:8000/docs>

## 4. 启动前端

第一次启动或依赖变化后，进入前端目录安装依赖：

```powershell
Set-Location apps/web
npm install
```

启动开发服务器：

```powershell
npm run dev
```

打开：<http://localhost:3000>

如果 API 不在默认地址，可以设置：

```powershell
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm run dev
```

## 5. 验证一条完整流程

1. 打开 <http://localhost:3000>。
2. 创建一门课程。
3. 进入课程，创建一节课次。
4. 打开课次详情。
5. 在支持浏览器语音识别的浏览器中点击“开始录音”，允许麦克风权限并说一段中文。
6. 点击“结束录音”，等待音频和已确认的浏览器识别文字保存。
7. 在“文字记录”区域查看识别结果。

也可以直接选择已有音频文件。配置 `DASHSCOPE_API_KEY` 后，后台会调用阿里云百炼 Paraformer 文件转写；浏览器录音没有产生已确认文字时同样会走该流程。转写完成后再生成智能纪要。

### 课程级问答

课程详情页的“问一问”会检索本课程已整理的课堂内容，并把回答引用链接到文字记录和录音时间点。问答需要在根目录 `.env` 同时配置 `DASHSCOPE_API_KEY`（文本向量）和 `DEEPSEEK_API_KEY`（生成回答）。首次升级后，已有课次在课程详情页点击“整理或更新课程资料”建立索引；新课次的转写和纪要会自动触发索引。索引由 Worker 异步完成，提交后稍等并刷新页面查看片段数量。

本地数据库使用带 pgvector 扩展的 PostgreSQL 16 镜像；首次升级执行 `docker compose up --build -d` 会下载新镜像并保留原有 `postgres_data` 数据卷。向量列固定为 1536 维，对应默认 `text-embedding-v2`；更换向量模型前需要迁移向量列并重建全部索引。

## 6. 查看日志

查看所有服务日志：

```powershell
docker compose logs -f
```

只看 API：

```powershell
docker compose logs -f api
```

只看 Worker：

```powershell
docker compose logs -f worker
```

按 `Ctrl+C` 退出日志查看，不会停止服务。

## 7. 停止和重新启动

停止容器但保留数据：

```powershell
docker compose down
```

下次启动：

```powershell
docker compose up -d
```

如果修改了后端依赖或 Dockerfile，需要重新构建：

```powershell
docker compose up --build -d
```

停止前端开发服务器，在运行 `npm run dev` 的终端按 `Ctrl+C`。

## 8. 数据保留规则

当前数据保存在 Docker 持久化卷：

- `classagent_postgres_data`：数据库数据
- `classagent_audio_data`：上传的音频文件

普通的 `docker compose down` 不会删除这些数据。不要在需要保留数据时执行：

```powershell
docker compose down -v
```

`down -v` 会删除 Compose 管理的卷，课程、课次和本地上传音频可能无法恢复。

## 9. 常见问题

### Docker 命令提示无法连接引擎

启动 Docker Desktop，等待状态变为运行中，再执行：

```powershell
docker compose up --build -d
```

### 页面提示无法连接后端

检查 API：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

如果失败，查看日志：

```powershell
docker compose logs --tail=100 api worker
```

### API 启动时提示 PostgreSQL 连接失败

查看状态：

```powershell
docker compose ps
```

等待 `postgres` 变为 `healthy` 后重建 API：

```powershell
docker compose up -d --force-recreate api worker
```

### 端口被占用

当前默认端口：

- 前端：3000
- API：8000
- PostgreSQL：5432
- Redis：6379

查看端口占用：

```powershell
Get-NetTCPConnection -LocalPort 3000,8000,5432,6379 -State Listen
```

### 页面显示旧内容或出现开发构建异常

停止前端后，删除 Next.js 本地缓存再重新启动：

```powershell
Set-Location apps/web
Remove-Item -Recurse -Force .next
npm run dev
```

## 10. 当前版本边界

- 当前没有账号登录和多用户隔离。
- 当前录音使用浏览器实时语音识别；直接上传已有音频使用阿里云百炼 Paraformer 文件转写，不生成模拟文字。
- 智能纪要可根据已保存的文字记录生成；搜索和课程问答尚未接入。
- 本地开发默认使用 Docker 持久化卷保存音频；生产环境再切换到 S3 兼容对象存储。
