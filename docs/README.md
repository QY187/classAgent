# 文档索引

从 [项目 README](../README.md) 了解当前功能和快速启动，再按主题查阅下列文档。目录内按三位编号排列，文件名保留原主题便于 Git 历史追踪。

## 分类与编号规则

- 每个主题目录独立从 `001` 编号，格式为 `001-主题.md`；本文件是统一导航入口，不参与业务文档编号。
- 本次初始编排优先采用文档标题或开头明确标注的原始日期，无标注时使用文件首次进入 Git 的作者日期；不使用磁盘修改时间，也不将最近更新时间当作创建日期。下表同时记录日期来源。
- 同一天的文档按原文件名稳定排序。编号表示该主题内的历史顺序，不代表优先级、实现阶段或最新版本。
- 后续新增文件使用目录内下一个编号，在索引中补充日期及说明；已有文件继续原地修订，不因修改日期或补录历史材料重排全部编号。
- 同一主题的后续说明优先更新现有文档，确需独立记录时再新增编号。产品需求保留已确认的核心范围；规划、历史测试和上线状态应明确区分。
- 文件迁移或改名时同步更新本索引、README、文档间相对链接、配置示例及协作指引中的路径。历史验证结果只说明当时验证范围，不以文件位置或编号推断已经上线。

## 常用入口

- [启动与本地配置](开发与部署/001-local-development.md)
- [当前生产基线、发布与回退](开发与部署/003-production-deployment.md)
- [录音、转写与纪要](纪要与转写/002-recordings-and-summaries.md)
- [课程表与 OCR 导入](课程/004-timetable.md)
- [课程 PDF 预览与导出](课程/003-course-export.md)
- [问答记忆与管理](问答与Agent/015-agent-memory.md)

## 产品与规划

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-09-28 | 文档标注 | [ClassAgent 产品初版报告 v0.3](产品与规划/001-product-brief-v0.3.md) |
| 002 | 2026-09-28 | 文档标注 | [ClassAgent 技术栈方案 v0.1](产品与规划/002-technical-stack-plan-v0.1.md) |
| 003 | 2026-10-01 | 首次 Git 提交 | [ClassAgent 后续功能规划 v0.1](产品与规划/003-feature-roadmap-v0.1.md) |

## 课程

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-10-03 | 首次 Git 提交 | [回收站模块说明](课程/001-recycle-bin-design.md) |
| 002 | 2026-10-22 | 首次 Git 提交 | [课程库首页统计](课程/002-home-overview.md) |
| 003 | 2026-11-19 | 首次 Git 提交 | [课程打包导出](课程/003-course-export.md) |
| 004 | 2026-11-26 | 首次 Git 提交 | [课程表与课表导入](课程/004-timetable.md) |

## 纪要与转写

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-11-18 | 首次 Git 提交 | [课堂资料导出格式](纪要与转写/001-lesson-export.md) |
| 002 | 2026-11-25 | 文档标注 | [录音、文字记录与智能纪要](纪要与转写/002-recordings-and-summaries.md) |

## 课件与检索

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-09-30 | 首次 Git 提交 | [课程级 RAG 问答 · 详细技术方案](课件与检索/001-course-rag-design.md) |
| 002 | 2026-10-30 | 首次 Git 提交 | [RAG 切块、召回与评测说明](课件与检索/002-rag-chunk-retrieval-evaluation.md) |
| 003 | 2026-10-30 | 首次 Git 提交 | [ClassAgent RAG 流程说明](课件与检索/003-rag-flow-overview.md) |
| 004 | 2026-10-30 | 首次 Git 提交 | [ClassAgent 课程 RAG 技术方案](课件与检索/004-rag-technical-solution.md) |
| 005 | 2026-11-09 | 首次 Git 提交 | [课件解析与问答](课件与检索/005-material-question-answering.md) |

## 问答与Agent

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-10-02 | 首次 Git 提交 | [ClassAgent Agent 核心功能设计 v0.1](问答与Agent/001-agent-core-design-v0.1.md) |
| 002 | 2026-10-08 | 首次 Git 提交 | [课程与课次问答工作台](问答与Agent/002-chat-workspace-design.md) |
| 003 | 2026-10-11 | 首次 Git 提交 | [Agent 工具基础](问答与Agent/003-agent-tools-foundation.md) |
| 004 | 2026-10-12 | 首次 Git 提交 | [主对话与跨课程范围](问答与Agent/004-global-chat.md) |
| 005 | 2026-10-14 | 首次 Git 提交 | [主对话与课程对话工具执行进度](问答与Agent/005-agent-progress.md) |
| 006 | 2026-10-14 | 首次 Git 提交 | [课程对话接入 Agent](问答与Agent/006-course-agent.md) |
| 007 | 2026-10-16 | 首次 Git 提交 | [Agent 查询学习记录](问答与Agent/007-agent-learning-records.md) |
| 008 | 2026-10-17 | 首次 Git 提交 | [Agent 课程管理](问答与Agent/008-agent-course-management.md) |
| 009 | 2026-10-18 | 首次 Git 提交 | [Agent 多项读取结果组合](问答与Agent/009-agent-combined-answers.md) |
| 010 | 2026-10-18 | 首次 Git 提交 | [Agent 最终响应与协议修复](问答与Agent/010-agent-responses.md) |
| 011 | 2026-10-22 | 首次 Git 提交 | [Agent 资料处理与小测工具](问答与Agent/011-agent-workflow-tools.md) |
| 012 | 2026-10-28 | 首次 Git 提交 | [Agent 自然语言入口补齐](问答与Agent/012-agent-natural-language.md) |
| 013 | 2026-10-30 | 首次 Git 提交 | [ClassAgent Agent 技术路线](问答与Agent/013-agent-technical-solution.md) |
| 014 | 2026-11-05 | 首次 Git 提交 | [Agent 多模型接入](问答与Agent/014-agent-models.md) |
| 015 | 2026-11-24 | 首次 Git 提交 | [Agent 记忆机制](问答与Agent/015-agent-memory.md) |

## 复习与小测

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-10-10 | 首次 Git 提交 | [课堂小测出题设置](复习与小测/001-quiz-generation-settings.md) |
| 002 | 2026-10-10 | 首次 Git 提交 | [错题连续重练](复习与小测/002-wrong-question-practice.md) |
| 003 | 2026-10-14 | 首次 Git 提交 | [通过主对话与课程对话生成课堂小测](复习与小测/003-agent-quiz.md) |

## 开发与部署

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-09-29 | 首次 Git 提交 | [ClassAgent 本地开发启动说明](开发与部署/001-local-development.md) |
| 002 | 2026-11-02 | 首次 Git 提交 | [Agent 请求级追踪与指标统计](开发与部署/002-agent-observability.md) |
| 003 | 2026-11-03 | 首次 Git 提交 | [生产部署操作手册](开发与部署/003-production-deployment.md) |
| 004 | 2026-11-03 | 首次 Git 提交 | [用户每日大模型 Token 额度](开发与部署/004-token-quotas.md) |
| 005 | 2026-11-10 | 首次 Git 提交 | [正式域名接入](开发与部署/005-domain-setup.md) |

## 界面与交互

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-11-10 | 首次 Git 提交 | [手机端布局](界面与交互/001-mobile-layout.md) |

## 验证与记录

| 编号 | 编排日期 | 日期来源 | 文档 |
| --- | --- | --- | --- |
| 001 | 2026-10-04 | 文档标注 | [Agent 正确性与准确性测试报告（2026-10-04）](验证与记录/001-agent-accuracy-audit-2026-10-04.md) |
| 002 | 2026-10-04 | 文档标注 | [Agent 扩展准确性测试（2026-10-04）](验证与记录/002-agent-expanded-audit-2026-10-04.md) |
| 003 | 2026-10-22 | 首次 Git 提交 | [问答工作台 Agent 全量对抗式测试报告](验证与记录/003-agent-adversarial-test-report.md) |
| 004 | 2026-11-23 | 文档标注 | [fxy 分支功能更新记录（2026-11-23）](验证与记录/004-fxy-update-2026-11-23.md) |
