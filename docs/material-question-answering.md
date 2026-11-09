# 课件解析与问答

## 后台处理基础

课件沿用原上传与存储入口，原文件先保存，再登记 `material_processing` 任务。支持文字型 PDF、PPTX、DOCX、TXT、Markdown；图片和旧版 Office 仍可保留、预览或下载，不会显示为可用于问答。扫描 PDF 没有可提取文字时提示暂不支持 OCR。图片、图表及复杂公式的含义不作识别承诺。

PDF 保留物理页码，PPTX 保留幻灯片展示顺序；DOCX、文本按段落定位。每文件最多 2000 页/幻灯片/段落、100 万字，Office XML 解压内容最多 32 MB，保留原上传 25 MB 限制。超限明确失败，不静默截断为完整资料。

`material_processing` 和 `material_chunks` 为新增独立表，由既有启动建表流程创建。处理状态为 stored（存量未处理）、queued、processing、indexing、ready、failed、unsupported；文件存储状态仍独立保留。

上传自动提交后台任务；`POST /courses/{course_id}/materials/{material_id}/index` 用于存量资料补建与失败重试，返回 202。活动任务不重复登记。队列不可用时保留数据库登记，beat 每分钟最多补投递 50 项；超过十分钟未结束的处理中任务换代重投。worker 软/硬时间限制为 240/270 秒。

任务先原子认领 generation，再解析和向量化，最后在同一事务切换 active_version 和内容块。失败保留上一可用版本；旧任务不能覆盖新任务。错误信息不暴露供应商异常。文件、课程或所属课次在回收站时，内容与处理记录均不可读取；彻底删除依赖数据库外键级联清理。

## 验证

`tests/test_material_indexing.py` 覆盖文本/Office 定位、空白及加密 PDF、队列失败后登记保留、重复执行、重建失败保留旧版以及回收站过滤；`test_materials.py` 验证原文件流程兼容。网络向量化边界使用模拟，不涉及真实用户资料或线上操作。
