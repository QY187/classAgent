# 课程级 RAG 问答 · 详细技术方案

> 当前问答入口已统一至问答工作台，使用 `POST /chat/conversations/{conversation_id}/ask`。下文的旧 `POST /courses/{course_id}/ask` 为初版设计记录，该接口和旧页面组件已删除；共用检索服务、索引状态和重建接口继续保留。

> 路线图项 **C**：把一门课程下所有课次的转写文字与智能纪要向量化，支持对整门课提问并给出**带引用（课次 + 时间戳）**的回答。
> 状态：初版已实现，后续以真实课堂样本验证检索与回答质量。适用分支：`main`。

---

## 1. 背景与目标

### 1.1 当前能力边界
现有产品已经做到：
- 单课次浏览器录音 → 转写（`transcript_segments`，含 `start_ms / end_ms / speaker / text`）
- 单课次智能纪要（`lesson_summaries.content`，结构化 JSON，含 `source_indexes` 回链转写序号）
- 转写片段点击定位播放（A 项，播放器 `seek` 到 `start_ms`）
- 跨课次全文搜索（B 项，`/search?q=`，基于 `ILIKE` 关键词）
- 多用户隔离（D 项，课程按 `owner_username` 归属）

**缺口**：用户只能「逐篇翻纪要」或「关键词搜」。无法用自然语言问「这门课老师反复强调过哪些易错点」「前两节和第三节在讲法上有什么承接关系」这类需要**跨多课次综合理解**的问题。

### 1.2 目标
- 对单门课程整体提问，答案基于该课程全部课次的转写 + 纪要
- 每条结论可追溯到具体课次、具体时间戳，点击跳转回对应转写片段并定位播放
- 仅用课堂真实内容作答，不编造；证据不足时明示「记录中未提及」
- 增量维护：新课程次转写/纪要生成后自动进入检索库，无需手工操作
- 支持存量数据一次性补跑

### 1.3 非目标（本期不做）
- 跨课程统一问答（仅限单课程内）
- 多轮深度对话记忆与个性化复习规划
- 流式回答（先返回完整答案，后续可加 SSE）
- 重排模型 / 重向量库（小数据量下 top-k 足够）

---

## 2. 现状调研（已实现基础，直接复用）

| 能力 | 位置 | 复用方式 |
|---|---|---|
| LLM 调用 | `apps/api/app/modules/summaries/service.py:70` | 直接 `httpx.post("https://api.deepseek.com/chat/completions")`，Bearer 鉴权，请求 `{model, messages, temperature}`，返回 `choices[0].message.content` |
| 异步任务 | `apps/api/app/infrastructure/tasks.py` | Celery + Redis（`celery_app`），`process_audio` 转写完成后 `generate_summary.delay(lesson.id)`（第 57 行） |
| Embedding | 无 | **需新增**；DeepSeek 无 embedding 接口 |
| 课程归属 | `courses.owner_username`（`models.py:31`） | 问答接口复用 `get_current_user` 做 owner 校验 |
| 前端定位 | 播放器 `seek`（`components/AudioPlayer.tsx`） | 引用跳转复用 |
| 配置 | `core/config.py`（`get_settings()`） | 新增 embedding 相关字段 |

**关键事实**：
- `TranscriptSegment`：`lesson_id, speaker, start_ms, end_ms, text, source`（`models.py:79`）
- `LessonSummary.content`：结构化 JSON 字符串，`chapter_flow / topics / examples / key_concepts / teacher_emphasis` 等字段都带 `source_indexes`（`summaries/service.py:14` 的 `SUMMARY_SCHEMA`），可回链转写序号 → 时间戳
- docker-compose：Postgres `postgres:16-alpine`、Redis `redis:7-alpine`、api + worker 两个服务（`docker-compose.yml`）

---

## 3. 总体架构

```
                   ┌─────────────────────────────────────────────┐
                   │             apps/web 课程详情页               │
                   │   「问一问」面板：输入框 / 回答 / 引用跳转     │
                   └───────────────┬─────────────────────────────┘
                                   │ POST /courses/{id}/ask
                                   ▼
                   ┌─────────────────────────────────────────────┐
                   │        modules/rag  (service + controller)    │
                   │  1. 问题 embedding                            │
                   │  2. pgvector 相似度检索 top-k（带元数据）      │
                   │  3. 组装 prompt → DeepSeek 生成（带引用标记）  │
                   └───────┬───────────────────────┬──────────────┘
                           │                        │
              ┌────────────▼─────────┐     ┌────────▼──────────────┐
              │  core/embeddings.py  │     │  DeepSeek chat 调用    │
              │  (复用 DASHSCOPE_KEY)│     │  (复用现有 httpx 模式) │
              └──────────────────────┘     └───────────────────────┘

   索引侧（写入）：
   process_audio 完成 / 纪要生成 / 转写编辑
              └──► reindex_lesson.delay(lesson_id)  [Celery]
                      └─► 取该课次 transcript+summary
                          └─► chunking + embedding
                              └─► upsert document_chunks (pgvector)
```

写入（索引）与读取（问答）解耦：索引走 Celery 异步，问答走同步 HTTP，互不阻塞。

---

## 4. 技术选型与理由

| 维度 | 选型 | 理由 |
|---|---|---|
| 向量存储 | **pgvector**（替换 Postgres 镜像为 `pgvector/pgvector:pg16`） | 不引入新数据库，运维成本最低；与现有 Postgres 同源；`<=>` 余弦距离运算符开箱即用 |
| Embedding 模型 | **通义千问 `text-embedding-v2`**（OpenAI 兼容接口） | 复用已配置的 `DASHSCOPE_API_KEY`，零新增密钥；`text-embedding-v2` 输出 1536 维。备选：`text-embedding-v3`（1024/1536 维）或 OpenAI `text-embedding-3-small`（需 `OPENAI_API_KEY`） |
| Embedding SDK | 直接 `httpx` 调 DashScope 兼容端点 | 与现有 DeepSeek 调用风格一致，不引新依赖 |
| 生成模型 | **DeepSeek chat**（复用现有） | 已验证可用，中文课堂语境质量好 |
| 向量索引 | `ivfflat`（先）或 `hnsw` | 数据量小，ivfflat 建索引快、够用；数据增长后可换 hnsw |
| Python 依赖 | 新增 `pgvector`（SQLAlchemy 的 `Vector` 类型支持） | 唯一新增依赖 |

**维度锁定**：向量列维度必须与 embedding 模型输出一致。固化到配置 `embedding_dim`，初期设 `1536`（对应 `text-embedding-v2`）；换模型需重建 `document_chunks` 表并重跑全量索引。

---

## 5. 数据模型详细设计

### 5.1 SQLAlchemy 模型（`shared/models.py` 新增）
```python
from pgvector.sqlalchemy import Vector

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(String(36), index=True)   # 冗余，检索免 join
    lesson_id: Mapped[str] = mapped_column(String(36), index=True)
    chunk_type: Mapped[str] = mapped_column(String(20))             # 'transcript' | 'summary'
    content: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)           # source_indexes 等
    embedding: Mapped[list[float] | None] = mapped_column(Vector(get_settings().embedding_dim), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
```

### 5.2 启动迁移（`main.py` 轻量 DDL，沿用现有 `create_all` 风格，不加 alembic）
```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- DocumentChunk 表由 Base.metadata.create_all 创建（含 Vector 列）
CREATE INDEX IF NOT EXISTS ix_document_chunks_course ON document_chunks (course_id);
-- 向量索引（数据量 > 数千条时建；ivfflat 需先有数据）
CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding
  ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```
> 注：ivfflat 空表建索引会报错，故首次启动仅建扩展与普通索引，向量索引在全量补跑（`reindex_course`）后再建；或改用 hnsw（`USING hnsw`），hnsw 支持空表建索引，推荐优先。

### 5.3 隔离与权限
`document_chunks.course_id` 对应课程的 `owner_username` 即数据归属方；问答接口先校验「课程属于当前用户」再检索，天然保证**用户只能问到自己课程的内容**。

---

## 6. Embedding 方案（`core/embeddings.py` 新增）

```python
import httpx
from ..core.config import get_settings

def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化，复用 DASHSCOPE_API_KEY。"""
    settings = get_settings()
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法生成向量")
    resp = httpx.post(
        f"{settings.dashscope_base_url}/compatible-mode/v1/embeddings",  # 或各自端点
        headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
        json={"model": settings.embedding_model, "input": texts},
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Embedding 请求失败（{resp.status_code}）：{resp.text[:300]}")
    data = resp.json()["data"]
    # 按输入顺序排序后返回
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
```
配置新增（`core/config.py`）：
```python
embedding_provider: str = "dashscope"      # dashscope | openai
embedding_model: str = "text-embedding-v2"
embedding_dim: int = 1536
```

---

## 7. 切块策略（Chunking）

目标：让每个块语义完整、可定位、检索噪声小。

### 7.1 转写块（transcript）
- 把同一课次的 `transcript_segments` 按**时间窗口**合并（默认 ~3 分钟 / 约 400 字一段；超过则强制切段）
- 块内容前缀：`[{课次标题} · {mm:ss}] {说话人}：` 后接合并文本
- 块元数据：`start_ms / end_ms / speaker / {lesson_title}`
- 这样检索命中的片段天然带可点击的时间戳

### 7.2 纪要块（summary）
- 解析 `lesson_summaries.content`（JSON），按**结构字段**拆块：
  - `overview` → 1 块
  - `topics[]` 每项 → 1 块（含 summary / points / takeaway）
  - `examples[]` 每项 → 1 块
  - `key_concepts[]` 每项 → 1 块
  - `teacher_emphasis / key_takeaways / assignments` → 各聚合为 1 块
- 每块元数据保留 `source_indexes`（纪要里已有的转写序号），构建引用时再映射回该课次的 `start_ms`
- `chunk_type = 'summary'`，`start_ms` 可由 `source_indexes` 对应转写段推算

### 7.3 块大小取舍
- 太小（<100 字）：上下文破碎，生成答案缺连贯；检索噪声低
- 太大（>800 字）：一段命中多个主题，引用不精确
- 先用上述「时间窗口 + 结构字段」双路，top-k=6；若实测召回不准，再调窗口或加关键字 rerank（见 §9）

---

## 8. 索引流水线（写入侧）

### 8.1 触发点
| 触发事件 | 位置 | 动作 |
|---|---|---|
| 音频转写 + 纪要生成完成 | `tasks.py: process_audio` 末尾 | `reindex_lesson.delay(lesson.id)` |
| 手动生成纪要完成 | `tasks.py: generate_summary` 末尾 | `reindex_lesson.delay(lesson.id)` |
| 转写被编辑 / 合并 | `modules/lessons/service.py` | 触发 `reindex_lesson.delay(lesson.id)` |
| 手动补跑 / 重试 | 新增 `POST /courses/{id}/reindex` | `reindex_course.delay(course_id)` 或单课次 |

### 8.2 Celery 任务（`infrastructure/tasks.py` 新增）
```python
@celery_app.task(name="classagent.reindex_lesson")
def reindex_lesson(lesson_id: str) -> None:
    # 1. 取 lesson + course_id + transcript_segments + lesson_summaries.content
    # 2. 切块（§7）
    # 3. 批量 embed_texts
    # 4. 先 DELETE 该 lesson 旧块，再 upsert 新块到 document_chunks
    # 原子替换，避免重复

@celery_app.task(name="classagent.reindex_course")
def reindex_course(course_id: str) -> None:
    # 遍历课程下所有课次，调用 reindex_lesson（串行即可，量小）
```
幂等：每次按 `lesson_id` 先删后插，重跑安全。

---

## 9. 问答检索与生成（读取侧）

### 9.1 检索
```sql
SELECT id, lesson_id, chunk_type, content, start_ms, end_ms, speaker, meta
FROM document_chunks
WHERE course_id = :course_id
ORDER BY embedding <=> :query_vec
LIMIT 6;
```
- `course_id` 过滤保证只检索本课程
- `<=>` 为 pgvector 余弦距离（越小越相似）

### 9.2 Prompt 设计（system）
> 你是课堂学习助手。只依据下方【课堂片段】回答用户问题，不得补充录音/纪要之外的内容，不得编造结论、日期、公式或人名。
> 每条实质结论后用 `[课次标题 @ mm:ss]` 标注来源（时间取片段 start_ms；若片段无时间则用课次标题）。
> 若提供片段不足以回答问题，明确说明「记录中未提及」，不要猜测。
> 用中文、条理清晰地回答。

user 消息：`问题：{question}\n\n课堂片段：\n{编号}. [课次标题 · mm:ss] 说话人：{content} ...`

### 9.3 引用回链
- 检索时已拿到每个块的 `lesson_id / lesson_title / start_ms`，直接作为 `citations` 返回，无需从模型输出里解析
- 前端点击 citation → `/lessons/{lesson_id}/transcript?t={start_ms}` → 复用 A 项的 `seek` 定位播放

### 9.4 重排（可选，暂不做）
数据量小，top-k=6 直接喂模型。若实测召回质量不足，可加一层：检索 top-20 → 用问题+片段做轻量交叉编码重排取 top-6。本期留接口不实现。

---

## 10. 接口设计（`modules/rag`）

### 10.1 问答
```
POST /courses/{course_id}/ask
Header: Authorization: Bearer <access_token>
Body:  { "question": "这门课老师强调过哪些易错点？", "history": [] }
Resp:  {
  "answer": "老师强调了…[当前代码测试 @ 03:12]…",
  "citations": [
    { "lesson_id": "uuid", "lesson_title": "第三节", "start_ms": 192000,
      "snippet": "这块要注意空指针…" }
  ]
}
```
- 校验课程归属（owner）；课程无块时返回明确提示「该课程还没有可检索的课堂内容，请先完成录音/转写」

### 10.2 重建索引
```
POST /courses/{course_id}/reindex
Body:  { "lesson_id": "uuid | null" }   # 不传则整门课程
Resp:  { "task_id": "...", "status": "queued" }
```

---

## 11. 前端设计（`apps/web`）

- **入口**：课程详情页（`/courses/[courseId]` 或现有课程工作台）新增「问一问」区块
- **交互**：
  - 输入框 + 发送按钮；展示问题、回答（Markdown 渲染）、引用列表
  - 引用卡片：显示「课次标题 · mm:ss + 片段摘要」，点击跳转转写页并定位
  - 空态：课程无索引时提示先完成录音
  - 加载态：问答请求 spinner
- **API 封装**：`lib/api.ts` 新增 `askCourse(courseId, question)` / `reindexCourse(courseId)`
- **复用**：跳转定位直接复用 A 项播放器 `seek`

---

## 12. 存量数据补跑与迁移

1. 部署新版本（含 `CREATE EXTENSION vector` + 新表）
2. 调用一次 `POST /courses/{course_id}/reindex`（或脚本遍历所有 owner 的全部课程）→ `reindex_course` 异步建向量
3. 之后所有新课程次走 §8 自动增量
4. 向量索引（hnsw）在补跑完成后确认生效

---

## 13. 涉及改动文件清单

| 层 | 文件 | 改动类型 |
|---|---|---|
| 部署 | `docker-compose.yml` | Postgres 镜像 → `pgvector/pgvector:pg16` |
| 依赖 | `apps/api/requirements.txt` | `+pgvector` |
| 配置 | `apps/api/app/core/config.py` | 新增 `embedding_provider/model/dim` |
| 模型 | `apps/api/app/shared/models.py` | 新增 `DocumentChunk` |
| 启动 | `apps/api/app/main.py` | 建 vector 扩展 + 表 + 向量索引 |
| Embedding | `apps/api/app/core/embeddings.py` | **新增**，统一向量化调用 |
| 任务 | `apps/api/app/infrastructure/tasks.py` | 新增 `reindex_lesson` / `reindex_course` |
| RAG | `apps/api/app/modules/rag/{service,controller,schemas}.py` | **新增**，检索 + 问答 |
| 路由 | `apps/api/app/main.py` 或模块注册 | 挂载 `/courses/{id}/ask`、`/reindex` |
| 触发 | `apps/api/app/modules/lessons/service.py`、`infrastructure/tasks.py` | 转写/纪要完成后触发 reindex |
| 前端 | 课程详情页 + `apps/web/lib/api.ts` | 「问一问」面板 |
| 文档 | `docs/course-rag-design.md` | 本文件 |

---

## 14. 风险与取舍

| 风险 | 应对 |
|---|---|
| 向量维度与模型不匹配 | 维度固化到配置；换模型必须重建表 + 全量重跑 |
| DashScope embedding 限流/不可用 | 复用现有 `dashscope_api_key`；失败抛错并在接口层友好提示；可选切 OpenAI |
| 小库检索质量 | top-k=6 + 时间窗口切块；必要时加关键字 rerank（接口预留） |
| 成本 | embedding 按 token 计费极低；问答每次 1 次 DeepSeek 调用，可接受 |
| 转写编辑后索引滞后 | 编辑即触发 `reindex_lesson`，异步最终一致；用户量少感知不到 |
| pgvector 镜像与现有数据卷 | 换镜像不丢数据（`postgres_data` 卷保留）；仅新增扩展 |

---

## 15. 实施步骤（建议分批）

1. **基础设施**：docker-compose 换 pgvector、加依赖与配置、`DocumentChunk` 模型、启动建表建扩展 → 验证服务起来、`\dx` 看到 vector
2. **Embedding + 切块**：`core/embeddings.py`、chunking 函数（转写窗口 + 纪要结构）
3. **索引任务**：`reindex_lesson` / `reindex_course`，接好触发点（process_audio / generate_summary / 转写编辑）
4. **问答接口**：`modules/rag` 检索 + DeepSeek 生成 + citations，owner 校验
5. **前端**：课程详情页「问一问」面板 + 引用跳转
6. **存量补跑**：全量 `reindex_course`，验证向量索引生效
7. **联调与测试**：单课程多课次提问、引用跳转、空态/无 key 降级

---

## 16. 测试建议

- 单测：`embed_texts` 返回维度正确；chunking 边界（空转写、超长段、纪要缺字段）
- 接口测：`/ask` 正常回答 + citations 时间戳正确；无归属课程返回 404；无 embedding key 返回友好错误
- 端到端：录 2~3 节课 → 自动索引 → 问跨课次问题 → 点击引用跳转到正确时间戳
- 回归：A/B/D 既有功能不受 pgvector 镜像切换影响
