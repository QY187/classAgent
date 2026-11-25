# 生产部署操作手册

适用于本项目后续线上发布。默认按下面的简化流程执行，根据实际改动补充验证，避免每次重新做全量业务验收。用户要求部署时执行发布；是否提交、推送仍遵循仓库约定，部署不等于授权推送。

## 一、当前生产基线

以下为2026-11-02发布完成时的状态。每次部署前读取实际运行容器，不能长期把此版本当成最新版本。

| 项目 | 当前值 |
| --- | --- |
| 线上地址 | `https://101.200.198.62` |
| SSH | `root@101.200.198.62`，使用现有密钥，不在文档记录凭证 |
| Compose项目 | `classagentprod` |
| 发布目录 | `/opt/classagent-releases/61ce07a` |
| 后端镜像 | `classagent-api:61ce07a`，api、worker、beat共用 |
| 前端镜像 | `classagent-web:61ce07a` |
| API访问方式 | 浏览器请求同源`/api`，由现有反向代理转发 |
| 前端生产参数 | `NEXT_PUBLIC_API_URL=/api`、`NEXT_PUBLIC_ALLOW_REGISTRATION=false` |
| 持久卷 | `classagentprod_postgres_data`、`classagentprod_redis_data`、`classagentprod_audio_data` |

生产Compose始终同时指定`.env.production`、`docker-compose.prod.yml`和`docker-compose.release.yml`。不要直接运行开发Compose，也不要用`latest`猜测线上版本。

当前前端镜像还包含一处打包修复：最终镜像复制`public/`，确保logo等资源存在。该修复已应用在线上，但记录本手册时仍未提交；后续构建必须确认它已经包含在发布输入中。

## 二、默认简化流程：五步完成

### 1. 确定发布范围

- 本地确认目标提交、未提交差异，以及上次线上版本。已通过且代码未变的功能测试直接复用，记录对应版本，不重复全量测试。
- 从线上容器读取实际镜像、Compose工作目录、配置文件及挂载信息，保存为本次发布的回退依据。
- 根据下一节判断需要更新哪些服务。仅文档变化时，无需部署。
- 默认从确定的Git版本导出源码；若包含用户要求上线的未提交修复，明确记录补丁和文件哈希，不能只标注原提交就当成完全相同的代码。

### 2. 只准备发生变化的产物

- 前端变化：在本机构建一次Linux amd64生产镜像，复用Docker依赖缓存，再上传、加载镜像。服务器内存较小，默认不在线上编译Next.js。
- 后端变化：依赖及系统环境未变时，可复用实际线上后端镜像的依赖，只替换完整应用目录；依赖、Python版本或Dockerfile系统包变化时，必须重新构建完整运行环境。
- 未变化的前端或后端，直接在发布覆盖文件中固定原镜像，不重复构建或上传。
- 新发布目录复制上一实际发布的生产配置，保留权限；不使用本地`.env`覆盖线上配置。若本次明确修改了配置，仅调整对应项。
- 发布包、镜像校验SHA256；确认生产API参数和`public/`资源。源文件清单与构建产物清单在准备阶段生成一次，验证结果复用。

### 3. 保存回退依据，更新应用服务

- 更新前保存旧应用镜像和Compose覆盖文件，保留旧镜像，记录配置及挂载信息。
- 后端或数据库变化前，完成数据库备份并验证归档可读取。纯前端发布不重复临时备份数据库，仍沿用既有备份安排。
- 首次镜像打包、新依赖或运行环境变化时，先运行候选容器检查启动和健康；普通改动复用已验证的构建方式。注意：本项目API启动可能初始化表结构，连接生产库的候选API也可能修改数据库，必须先审查并备份。
- 仅更新受影响的应用服务，使用`--no-deps --no-build`，不重建PostgreSQL、Redis或数据卷。
- 更新后端前检查worker的active/reserved任务，先停beat，再让worker正常完成退出。切换API后再启动worker/beat，避免重复调度；有长任务时先完成可独立更新的前端，等待窗口再更新后端，不强制中断任务。

### 4. 执行最小线上检查

每次发布默认只做以下检查：

1. **服务状态**：本次目标服务使用预期镜像、保持运行、无反复重启；日志无新增启动异常。
2. **公网健康**：首页、`/api/health`和本次改动页面响应正常；页面HTTP 200只代表页面可访问，不能替代业务接口检查。
3. **本次改动**：验证一个实际业务路径。界面改动检查实际页面；API改动检查对应接口；需要登录时检查真实授权结果。不能仅凭未登录页面200判定成功。
4. **后台检查**：仅更新worker时检查Celery ping；涉及后台任务逻辑时增加对应任务验证。

权限、额度等关键变化按下一节补测。普通页面调整不重新创建三套账号、不调用付费模型、不重跑整个Agent、RAG或ASR链路。

### 5. 收尾并反馈

- 仅清理本次创建的临时账号、关联资料、令牌和候选容器，保留正式发布、回退镜像和备份。
- 记录版本、实际部署补丁、服务、检查结果、回退位置、未覆盖范围和剩余本地修改；日志不记录密钥、密码或会话。
- 简短告知用户上线结果和访问地址，不等待额外全量验收完成才反馈。
- 若本次检查失败，先按第五节处理，再报告实际结果，不能将“容器已启动”表述成“部署成功”。

## 三、按改动决定构建和验证范围

| 改动 | 更新范围 | 在默认检查之外补充 |
| --- | --- | --- |
| 仅文档 | 无应用更新 | 链接、命令和差异检查 |
| 页面、样式、前端交互 | web | 目标页面和一次交互；涉及布局时检查手机宽度 |
| 普通后端业务，依赖不变 | api/worker/beat共用新后端镜像，保持版本一致 | 对应接口或工具路径；只有业务需要时调用模型 |
| 依赖、Python、系统包、镜像打包 | 受影响的镜像与服务 | 候选启动、导入、静态资源及对应运行功能 |
| 数据表或初始化逻辑 | 后端与相关服务 | 备份、结构兼容性、原数据保留、旧应用兼容性 |
| 登录、角色、数据归属 | 受影响服务 | 匿名保护、本人正常访问、另一用户越权被拒；有管理能力时补管理员验证 |
| Token额度或计量 | 受影响服务 | 正常结算、额度不足、幂等重放、其他用户不受影响；改到后台计量时验证真实worker |
| Agent或模型调用链 | 后端，必要时web | 一条代表性的真实模型/工具路径和失败信息；不自动扩展成全场景评测 |
| RAG检索或切块 | 后端及必要索引任务 | 固定小样本检查；切块/向量配置变化先确认旧索引兼容性和重建方案 |
| 转写或后台处理 | 后端 | 对应真实任务，确认失败状态与文件归属 |

同一版本同时涉及多类变化时，合并所需检查，去掉重复步骤。无法复用旧验证证据、首次接入大功能或出现异常时再扩大范围，不对每次部署机械执行全部项目。

## 四、常用命令

以下命令在**服务器Bash**中执行。目标发布目录和镜像必须已经准备好；这是切换命令示例，不是一键准备环境脚本。示例使用本次发布目录，后续需换成实际新目录。

```bash
release_dir=/opt/classagent-releases/61ce07a
compose=(docker compose -p classagentprod
  --env-file "$release_dir/.env.production"
  -f "$release_dir/docker-compose.prod.yml"
  -f "$release_dir/docker-compose.release.yml")

# 只查看运行信息，不输出生产环境变量。
"${compose[@]}" ps
docker inspect --format '{{.Config.Image}} {{.State.Status}} {{.RestartCount}}' classagentprod-api-1

# 仅前端变化时。
"${compose[@]}" up -d --no-deps --no-build web

# 后端变化：先查看任务；非空时先处理任务窗口，不直接继续停服务。
docker exec classagentprod-worker-1 celery -A app.infrastructure.tasks.celery_app inspect active
docker exec classagentprod-worker-1 celery -A app.infrastructure.tasks.celery_app inspect reserved
"${compose[@]}" stop -t 120 beat
# 再次确认active/reserved任务为空；若不为空，等待任务完成后再停worker。
"${compose[@]}" stop -t 120 worker
# 确认worker正常退出，无任务被超时强制终止后再继续。
"${compose[@]}" up -d --no-deps --no-build api
curl --fail --silent --show-error http://127.0.0.1:8000/health
# API就绪后启动后台服务。
"${compose[@]}" up -d --no-deps --no-build worker beat
docker exec classagentprod-worker-1 celery -A app.infrastructure.tasks.celery_app inspect ping

# 最小公网检查，curl非零退出或状态异常时停止并排查。
curl --fail --silent --show-error https://101.200.198.62/api/health
curl --fail --silent --show-error --output /dev/null https://101.200.198.62/
```

不要把前端与后端两组示例无差别整段执行。完整输出的`docker inspect`、`docker compose config`可能包含密钥，仅提取需要的非敏感字段。不得通过`down -v`、清理卷或覆盖配置来解决发布问题。

## 五、失败处理与回退

- **切换前失败**：停止发布，正式服务保持原状，修复构建或候选服务后继续；不反复重建生产服务试错。
- **切换后服务或本次关键功能失败**：先判断是否为新版本问题；确认后回退本次更新的服务到事先记录的镜像。使用同一个Compose项目、同一份生产env和基础配置，覆盖文件改用该发布目录`rollback/docker-compose.rollback.yml`。
- **数据库变化**：镜像回退不等于数据库回退。先确认旧代码兼容新结构；不兼容时采用兼容修复或明确的迁移回退方案，不自动用旧dump覆盖真实用户新数据。
- 回退后重复最小健康检查，记录实际回退版本和失败原因。

## 六、后续执行约定

后续默认采用“五步简化流程＋按改动补测”。构建、上传、切换和验证是不同阶段，同一版本相同产物不反复构建，相同证据不反复校验。修改产物、发生失败或出现新风险时才重跑对应检查。

可以并行执行独立的本地测试和前端构建准备；依赖它们的上传、切换必须顺序执行。涉及后端或数据库时的备份、配置保护、目标版本确认和失败回退不能为节省时间省略。耗时取决于构建缓存、上传带宽和后台任务，不承诺固定分钟数。

本文提供操作流程和命令示例，尚未实现全自动发布。2026-11-02完整部署证据保存在本地忽略目录`test-results/deployment-61ce07a-20261102/`，不作为后续发布必须重复执行的测试列表。

## 七、正式域名与备案页脚

正式入口为 `https://njust.shop`，HTTP 和 www 入口统一跳转至该 HTTPS 域名。备案号、版权展示、Nginx 配置、证书自动续期和域名回退说明见 `docs/domain-setup.md`。

2026-11-09 的域名接入采用线上 `92935e0` 基线，仅叠加三份备案页脚前端文件；前端镜像最终为 `classagent-web:92935e0-icp-20261109-r2`。后端仍为 `classagent-api:92935e0`，不能据此认为本地新增的课件问答能力已部署。完整发布与回退记录位于 `/opt/classagent-releases/92935e0-icp-20261109-r2/`，本地验证记录位于忽略的 `test-results/domain-njust-shop-20261109/`。

2026-11-10 已仅更新前端移动端布局，镜像为 `classagent-web:92935e0-mobile-6800f05-20261110`，发布目录 `/opt/classagent-releases/92935e0-mobile-6800f05-20261110/`。源码以线上 `92935e0` 业务及备案页脚为基线，叠加三笔移动端提交；资料组件仅接入兼容现有接口的手机操作菜单，没有顺带上线课件解析、替换和检索问答。后端及其余五个容器保持原标识、启动时间和挂载，Kombu 本地依赖修复未部署。实际发布源码26项测试、Linux镜像构建及类型检查通过；候选和公网390px/1440px各8项真实数据页面检查通过，无业务写入和模型调用。实际发布源码与哈希清单、构建及检查记录保存在发布目录的 `activation-evidence/`，本地报告见忽略目录 `test-results/deployment-mobile-20261110/report.md`。回退使用同目录 `rollback/docker-compose.rollback.yml`，原前端镜像保留；后续部署仍须读取实时运行状态。

## 八、出题与资料导出部署（2026-11-21）

已将完整提交 `fc924f5549bc26b7cb923c3f79dd29ad69e06e3e` 部署至 `https://njust.shop`。发布目录 `/opt/classagent-releases/fc924f5-20261121`，前端镜像 `classagent-web:fc924f5`，api、worker、beat 共用 `classagent-api:fc924f5`。本次包含课件出题所需的已推送课件解析、检索与替换能力，以及后台Kombu依赖修复；不再沿用上一版仅适配旧后端的移动端补丁。源码从该Git提交导出，无额外业务补丁。

前后端均在本机构建Linux amd64生产镜像，后端固定依赖与pip check、前端生产构建及类型检查通过；复用同源码已有回归结果。镜像及源码归档校验通过，候选API的158份源码/依赖哈希与发布输入一致，候选服务及新增结构检查通过。数据库新增三张课件处理表和小测课件引用可空字段；更新前保存并验证了 `rollback/database-before.dump`。生产env、数据挂载保持不变，PostgreSQL和Redis未重建。后台无active/reserved任务时完成正常切换。

公网代表性验收通过：上传文字课件、真实Worker解析及索引、Agent生成3道判断题、独立答案审核、作答及来源定位；匿名/越权保护、重放不重复计费与另一用户额度隔离通过。390/1440各5项共10项页面检查通过，涵盖文件选择、成绩引用、手动编辑纪要导出和PDF打印。四个应用无重启循环或新增关键日志错误，首页、登录页与健康接口正常。临时账号、资料、测验、消息、额度与追踪已清理，原27张表行数与发布前完全一致。

回退覆盖文件为本次发布目录下 `rollback/docker-compose.rollback.yml`，旧镜像及数据库备份保留；回退应用不自动覆盖数据库。完整说明和证据保存在本地忽略目录 `test-results/deployment-fc924f5-20261121/` 及线上发布目录的 `activation-evidence/`。本次只做代表性模型路径验收，不等于全场景出题质量评测。


## 九、课程四类PDF打包导出上线（2026-11-22）

已部署完整提交`1347ca830a0c48cd4e1d20704ada9e13582add60`至`https://njust.shop`，发布目录`/opt/classagent-releases/1347ca8-20261122`。web使用`classagent-web:1347ca8`，api、worker、beat共用`classagent-api:1347ca8`。源码由该Git提交归档，无未提交业务补丁；并行新对话开发的导出预览未包含在本次发布。

本次上线课程整门/指定课次ZIP打包、四类PDF内容勾选及新版阅读排版：智能纪要、知识点、小测题目、文字记录默认全选，不附原音频、课件、答案或解析。PDF依赖及中文字体随完整后端镜像构建，前端生产参数为同源`/api`并关闭注册入口；前后端Linux amd64镜像、固定依赖与pip check、前端构建及类型检查通过，复用同代码已有业务和排版验证。

切换前数据库备份`rollback/database-before.dump`为488585字节，pg_restore目录读取通过，SHA256为`acc7d0e786a8a1a931195d3b1c4ef92ee43467b16f4bfb9867fbc99d3e93b09f`。生产env逐字节保留；镜像及源码归档校验、165份后端源码/依赖哈希、候选API与web启动通过。确认后台active/reserved为空，先停beat、正常停止worker后切换应用；PostgreSQL、Redis及数据挂载保持不变。没有新增业务模型或数据库迁移。

公网验收通过：匿名401、其他用户404、回收站课次400、旧附件字段422；实际授权导出含四类PDF及课程目录，手动纪要和说话人保留，小测不泄露答案解析。390/1440宽度各实际下载一次ZIP，共10个PDF逐一核对并渲染，无浏览器异常或横向溢出。仅使用临时固定课堂样例，无模型调用；样例初次写入因遗漏既有必填字段回滚，补齐后通过，未修改产品代码。临时账号、资料、令牌及候选容器均清理，原30张表行数与发布前一致，四应用无新增关键日志异常或重启循环；首页、登录页、健康接口均200，Worker ping通过。

回退使用`/opt/classagent-releases/1347ca8-20261122/rollback/docker-compose.rollback.yml`，旧fc924f5镜像和数据库备份保留，不自动覆盖数据库。证据保存在本地忽略目录`test-results/deployment-1347ca8-20261122/`与线上`activation-evidence/`。本条为部署记录，单独本地提交；不代表再次授权推送或预览功能已上线。


## 十、PDF真实预览与稳定性修复上线（2026-11-22）

已部署完整提交`a78b8535a316aa472feb8f2409d73f9569f52368`至`https://njust.shop`，发布目录`/opt/classagent-releases/a78b853-20261122`。web为`classagent-web:a78b853`，api/worker/beat统一为`classagent-api:a78b853`。本次上线下载前真实PDF预览、页面内翻页与缩放，以及普通滚动条引起的持续重绘修复。Git提交日期此前按用户要求设为11月24日，实际发布发生在11月22日。

前端使用固定Git归档在本机构建Linux amd64镜像，生产编译、类型检查、同源`/api`、注册关闭、public及版本化PDF.js Worker资源验证通过。后端依赖、Dockerfile和模型未变，按简化流程复用已核实的线上`classagent-api:1347ca8`环境（镜像ID`9cf18bd80721fcacccf93674c2dbb4e1b29dc7a79f55f066f196a1891f458f4e`），在服务器移除旧应用并复制完整目标应用目录形成新镜像；requirements哈希、pip check和候选165份源码/依赖哈希与发布输入一致，无业务补丁或数据库迁移。

更新前备份`rollback/database-before.dump`488585字节，pg_restore目录可读，SHA256为`d3cb3ce472c77b017851871b4d146fcffb6d80514b71afd9a3844aa20d58ab6a`。生产env逐字节保留。候选API/web通过后，确认active/reserved为空，正常停止beat和worker再切换应用；PostgreSQL、Redis标识和启动时间、数据挂载不变。

公网临时固定资料验证：预览接口本人访问、匿名401、跨用户404、回收站400、非法文档404，课程目录及四类PDF正常，编辑内容和说话人保留，小测无答案解析。390/1440验证实际Canvas内容、5页纪要翻页、缩放和ZIP下载，页面异常与失败资源0；两份ZIP内10个PDF有效。普通15px滚动条稳定性专项在公网通过，静置/滚动无重复绘制、缩放时保留旧Canvas、窗口变化后稳定。复用同代码已通过的本地28项后端、42项前端及主项目验证，无模型调用。

临时账号、资料、令牌、候选容器及上传包已清理，原30张表行数与发布前一致，四应用无重启循环或新增关键日志异常，首页/login/api/health均200，Worker ping通过。回退使用本次目录`rollback/docker-compose.rollback.yml`，旧1347ca8镜像及数据库备份保留，不自动覆盖数据库。证据位于本地忽略目录`test-results/deployment-a78b853-20261122/`及线上`activation-evidence/`。本条仅部署记录，本地提交，不额外推送。


## 十一、问答记忆与课程表更新上线（2026-11-25）

已将基线 `3d490da5c7b95d1d24ec21ca5b7227da1085878c` 的问答记忆、课程表、扫描 PDF 本地 OCR、XLS 导入和自动搜索部署至 `https://njust.shop`。发布目录为 `/opt/classagent-releases/3d490da-20261125`，web 使用 `classagent-web:3d490da`，api/worker/beat 共用 `classagent-api:3d490da`。另包含前端记忆开关保存修复 `a2f2792c7cd2d29194acabef101314d3ece1e16f`：只提交两个可写设置字段，避免接口响应中的只读 temporary 字段导致 422；该修复与本条部署记录仅本地提交，未另行推送。发布清单记录基线、补丁及对应提交；前端修复文件的归档与构建输入仅换行形式不同，内容一致。

前后端均在本机完成 Linux amd64 生产构建。后端依赖和系统包发生变化，已完整重建运行环境，pip check 及 OCR/PDF/XLS 模块导入通过。下载超时、不完整字体包与上传链路波动导致本次准备耗时较长；最终依赖校验和安装成功。前端构建、类型检查、同源 /api、关闭注册与 public 资源检查通过，已有同代码回归结果复用。

前端镜像直接上传加载。后端完整镜像压缩包为 597610887 字节，为减少传输改为上传 327171098 字节的文件增量，在服务器离线还原完整本地构建环境，没有在线下载依赖或编译。增量 SHA256 为 `a528a9e90972047dbea4130e1e3e0a27368845ab96aeb04660350c7f5c194ffb`。本地与服务器分别核对 28333 个文件/目录项的内容、权限、归属、链接及运行配置，一致性检查通过；最终后端镜像 ID 为 `ccfe34b47f7d96d5d55df83b52da79eb39d14b6a234b9ce155cb958d79722db9`。原始完整构建镜像、传输与还原镜像的各自标识均有记录，不以不同的镜像 ID 冒充同一镜像。

候选服务连接生产库之前，重新保存并验证 `rollback/database-before-candidate.dump`（490242 字节，SHA256 `ea4eca2fbe1a94fb8ebb67d0b72daba1b03333804a95dedc7e8c24ccf69aa695`）；较早的首次备份也保留。新增记忆、课表等结构检查和候选 API/web 启动通过，188 份后端源码/依赖哈希与发布清单相符。生产 env 原样保留。首次切换的 Worker 在线检查未及时响应，脚本自动回退；增加有界启动等待后重试成功。确认 active/reserved 为空，正常停止 Beat/Worker，再更新四个应用服务；PostgreSQL、Redis 标识/启动时间及数据挂载未改变。

按用户明确要求跳过业务验收，没有创建测试业务数据或调用模型。仅完成部署检查：首页、登录、课表、记忆管理、问答页面及 /api/health 均 200，Worker ping 通过，四个应用无重启循环或新增关键日志错误，原 30 张表行数未变。页面 200 不代表业务链路已验收。候选容器、私有候选 env、上传分块/大包和未执行的样例已清理。回退仍使用本次目录 `rollback/docker-compose.rollback.yml`，保留旧 a78b853 镜像及数据库备份；不自动恢复数据库。证据位于本地忽略目录 `test-results/deployment-3d490da-20261125/` 和线上 `activation-evidence/`。
