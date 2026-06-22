# AMAS 企业级开发路线图

文档日期：2026-06-12

本文档用于指导 AMAS 从当前的原型级 Agentic Workflow 项目，逐步扩展为可交付、可运维、可审计、可规模化的企业级智能调研与报告生成平台。

## 1. 当前项目定位

AMAS 当前已经具备一个清晰的 Agentic Workflow 骨架：

- 后端使用 FastAPI 提供 API 与 SSE 流式输出。
- Agent 编排默认基于纯 Python Workflow Engine，采用中心状态机统一调度；LangGraph 已降级为 legacy fallback，用于灰度回滚和行为对照。
- 主流程为 Router、Planner、Researcher、Writer、Reviewer、Refiner。
- 已支持本地文档 RAG、网络搜索、报告生成、审查回环、报告局部修改。
- 已加入会话级记忆、滑动窗口、语义记忆、Token 预算管理等上下文工程能力。
- 前端使用 Vue 3、Vite、Tailwind CSS，具备聊天式交互与报告展示能力。

从架构范式看，它不是 Swarm，而是一个 Supervisor-style 的多节点状态机工作流：由中心图结构负责路由和流程控制，各节点承担专业职责。

## 2. 企业级目标

企业级版本不只是“功能更多”，核心是让系统具备以下能力：

- 可靠：Agent 执行失败可恢复，输出质量可评估，服务异常可定位。
- 安全：用户、文档、会话、API Key 和模型调用都可控。
- 可扩展：支持多租户、多知识库、多模型、多任务并发。
- 可运维：有日志、指标、链路追踪、告警、灰度发布和回滚。
- 可治理：有权限、审计、数据生命周期、合规策略。
- 可产品化：有清晰的工作台、历史资产、团队协作、导出和管理后台。

## 3. 成熟度评估

| 模块 | 当前状态 | 企业级缺口 | 优先级 |
|---|---|---|---|
| Agent 编排 | 已有 Python Workflow Engine、Harness Registry、Tool Runtime，保留 LangGraph legacy fallback | 需要继续强化工作流版本治理、灰度回滚策略、执行追踪分析和回归评测 | P0 |
| RAG | 已有本地文档检索和相关性判断 | 缺少多知识库、权限隔离、文档增量索引、引用溯源 | P0 |
| 会话记忆 | 已有 Redis 会话、分层记忆、压缩摘要 | 缺少长期持久化、租户隔离、记忆治理策略 | P0 |
| API | 已有 chat、upload、session 等接口 | 缺少统一错误码、鉴权、限流、API 版本化 | P0 |
| 安全 | 当前偏开发环境 | 缺少认证授权、密钥托管、上传安全、审计日志 | P0 |
| 测试 | 暂未形成系统化测试体系 | 缺少单元、集成、E2E、Agent 回归评测 | P0 |
| 前端 | 已有基础聊天和展示界面 | 缺少企业工作台、权限视图、任务中心、知识库管理 | P1 |
| 部署 | 当前适合本地运行 | 缺少 Docker、CI/CD、环境分层、蓝绿发布 | P1 |
| 可观测性 | 主要依赖 print | 缺少结构化日志、指标、Trace、成本看板 | P1 |
| 合规 | 暂无系统设计 | 缺少数据脱敏、保留策略、删除策略、访问审计 | P1 |

## 4. 总体架构演进方向

建议将系统拆成以下逻辑层：

```text
Frontend Workspace
    |
API Gateway / Backend API
    |
Auth, Tenant, Rate Limit, Audit
    |
Agent Orchestrator
    |-- Workflow Registry
    |-- Node Runtime
    |-- Tool Runtime
    |-- Evaluation Hooks
    |
Knowledge Platform
    |-- Document Service
    |-- Vector Index Service
    |-- Retrieval Service
    |-- Citation Service
    |
Memory Platform
    |-- Session Store
    |-- Turn Store
    |-- Semantic Memory
    |-- Compression Jobs
    |
Model Gateway
    |-- Provider Routing
    |-- Fallback
    |-- Cost Control
    |-- Prompt Versioning
    |
Observability Platform
    |-- Logs
    |-- Metrics
    |-- Traces
    |-- Alerts
```

## 5. 第一阶段：工程底座加固

目标：让项目从“能跑”变成“稳定可开发、可测试、可部署”。

### 5.1 配置管理

开发内容：

- 增加统一配置模块，例如 `app/core/config.py`。
- 使用 Pydantic Settings 管理环境变量。
- 区分 `local`、`dev`、`staging`、`prod` 环境。
- 将模型、Redis、向量库、搜索服务、上传限制、Token 预算等全部配置化。
- 禁止业务代码直接读取散落的 `os.getenv`。

验收标准：

- 修改环境只需要切换 `.env` 或部署环境变量。
- 服务启动时能打印脱敏后的配置摘要。
- 缺少关键配置时启动失败并给出明确错误。

### 5.2 项目结构重整

建议后端逐步演进为：

```text
backend/
  app/
    api/
      v1/
        routes_chat.py
        routes_sessions.py
        routes_knowledge.py
        routes_admin.py
    core/
      config.py
      security.py
      logging.py
      errors.py
    graph/
      graph.py
      state.py
      nodes/
    services/
      chat_service.py
      document_service.py
      session_service.py
      knowledge_service.py
      evaluation_service.py
    repositories/
      session_repo.py
      document_repo.py
      audit_repo.py
    models/
      schemas.py
      domain.py
    utils/
    tests/
```

验收标准：

- API 层只负责请求解析、响应格式和错误转换。
- 业务逻辑进入 service 层。
- 数据读写进入 repository 层。
- Graph 节点不直接关心 HTTP、Redis 连接细节和前端协议。

### 5.3 统一错误处理

开发内容：

- 定义标准错误结构：

```json
{
  "code": "DOCUMENT_TOO_LARGE",
  "message": "上传文件超过限制",
  "request_id": "req_xxx",
  "details": {}
}
```

- 增加全局异常处理器。
- 将 Agent 节点失败、工具失败、模型失败、检索失败区分为不同错误类型。
- SSE 中的 `__error__` 事件也使用统一结构。

验收标准：

- 前端可以基于 `code` 做稳定的错误提示。
- 日志中可以通过 `request_id` 关联一次请求。
- 用户看不到 Python traceback、密钥、内部路径。

## 6. 第二阶段：安全、租户与权限

目标：支持企业内部多用户、多团队使用。

### 6.1 用户认证

开发内容：

- 增加登录体系，支持 JWT 或企业 SSO。
- 用户表至少包含 `id`、`email`、`name`、`role`、`tenant_id`、`status`。
- 所有核心接口必须要求认证。
- 支持 Token 过期、刷新、退出登录。

验收标准：

- 未登录用户不能访问会话、上传、历史记录、知识库。
- 用户只能看到自己或所属团队授权的数据。

### 6.2 多租户隔离

开发内容：

- 所有会话、文档、知识库、任务、审计日志都增加 `tenant_id`。
- Redis Key、向量库 Collection、对象存储路径按租户隔离。
- 管理员可查看租户级用量和风险事件。

验收标准：

- 租户 A 无法读取租户 B 的文档、会话和向量索引。
- 测试覆盖跨租户越权访问。

### 6.3 RBAC 权限模型

建议角色：

| 角色 | 能力 |
|---|---|
| Owner | 管理租户、成员、账单、全局配置 |
| Admin | 管理知识库、查看团队任务、配置工作流 |
| Member | 创建会话、上传授权文档、生成报告 |
| Viewer | 只读查看授权报告和历史记录 |
| Auditor | 查看审计日志和合规报告 |

验收标准：

- 后端权限判断不依赖前端隐藏按钮。
- 关键操作写入审计日志。

### 6.4 上传安全

开发内容：

- 限制文件类型、大小、数量。
- 文件名规范化，避免路径穿越。
- 增加病毒扫描或恶意文件检测接口预留。
- 对 PDF、DOCX、TXT、Markdown 等解析过程做沙箱化和超时控制。
- 上传文件进入对象存储，数据库只存元数据。

验收标准：

- 恶意文件名不能写出上传目录。
- 解析失败不会影响主进程稳定性。
- 上传、删除、下载均有审计记录。

## 7. 第三阶段：知识库平台化

目标：把现在的“上传即重置知识库”升级为可管理的企业知识库。

### 7.1 多知识库

开发内容：

- 新增知识库实体：

```text
KnowledgeBase
  id
  tenant_id
  name
  description
  visibility
  embedding_model
  chunking_strategy
  created_by
  created_at
```

- 支持一个会话选择一个或多个知识库。
- 支持团队共享知识库和个人知识库。

验收标准：

- 上传新文档不会清空其他知识库。
- 用户能选择本次研究使用哪些知识库。

### 7.2 文档生命周期

开发内容：

- 文档状态：`uploaded`、`parsing`、`indexed`、`failed`、`archived`。
- 文档支持重试解析、重新索引、删除、归档。
- 文档元数据包括文件大小、页数、hash、版本、解析器版本。

验收标准：

- 前端能展示文档处理进度。
- 同一文件可通过 hash 去重。
- 删除文档后对应向量也会清理。

### 7.3 引用与溯源

开发内容：

- 检索结果必须包含 `document_id`、`chunk_id`、页码、段落位置。
- Writer 输出报告时保留引用编号。
- 前端点击引用可跳转到原文片段。
- Reviewer 检查报告中关键结论是否有证据支撑。

验收标准：

- 每个事实性结论尽量可追溯到文档或搜索结果。
- 无证据内容需要被标记为推断或不确定。

### 7.4 检索质量优化

开发内容：

- 支持 hybrid retrieval：关键词检索加向量检索。
- 增加 reranker。
- 支持按时间、标签、文档类型、权限过滤。
- 增加查询改写和多查询召回。
- 对检索结果做去重和上下文压缩。

验收标准：

- 有固定测试集评估 Recall、MRR、答案引用准确率。
- 检索配置可以灰度调整。

## 8. 第四阶段：Agent 运行时企业化

目标：让 Agent 不只是能生成，而是可控、可回放、可评估、可扩展。

### 8.1 工作流版本管理

开发内容：

- 每个工作流有 `workflow_id` 和 `version`。
- 节点 Prompt、模型、工具、预算、路由规则都纳入版本。
- 会话记录保存当时使用的工作流版本。
- 支持灰度发布新工作流。

验收标准：

- 历史任务可以按原工作流配置复现。
- 新工作流失败时可以回滚。

### 8.2 节点运行保护

开发内容：

- 每个节点支持超时、重试、熔断。
- Tool 调用有最大耗时和最大返回长度。
- LLM 输出解析失败有标准重试策略。
- Graph 执行有最大步数和最大总耗时。

验收标准：

- 单个节点卡住不会拖垮整个请求。
- Reviewer 回环不会无限循环。
- 节点失败能被清晰展示给用户和运维人员。

### 8.3 模型网关

开发内容：

- 增加统一 `ModelGateway`，封装不同模型供应商。
- 支持模型路由：低成本模型处理 Router，强模型处理 Writer。
- 支持 fallback：主模型失败时切换备用模型。
- 支持成本预算：按租户、用户、会话限制 Token 和金额。
- 记录每次调用的模型、输入 Token、输出 Token、耗时、费用估算。

验收标准：

- 业务代码不直接调用某个供应商 SDK。
- 可以按环境切换模型。
- 成本看板能按租户、用户、工作流统计。

### 8.4 Prompt 管理

开发内容：

- 将 Prompt 从代码中逐步抽出，进入版本化配置。
- Prompt 包含名称、版本、适用节点、变量 schema、评审状态。
- 支持 Prompt 回滚和 A/B 测试。

验收标准：

- 修改 Prompt 不需要改业务代码。
- 每次 Agent 执行都记录使用的 Prompt 版本。

## 9. 第五阶段：评测与质量体系

目标：避免 Agent 改一次坏一次，建立可持续迭代的质量闭环。

### 9.1 自动化测试

后端测试：

- 单元测试：状态路由、预算计算、文档解析、Redis Repository。
- 集成测试：上传、索引、检索、聊天 SSE、会话历史。
- 合约测试：API 响应结构和错误码。

前端测试：

- 组件测试：聊天输入、历史记录、报告渲染、知识库选择器。
- E2E 测试：上传文档、发起研究、查看报告、继续修改。

验收标准：

- 主分支合并前必须通过核心测试。
- 关键流程覆盖率达标。

### 9.2 Agent 回归评测

建立一组固定评测集：

```text
evals/
  cases/
    research_basic.yaml
    rag_grounding.yaml
    refine_report.yaml
    irrelevant_document.yaml
    multi_turn_memory.yaml
```

每个 case 包含：

- 用户问题。
- 输入文档。
- 期望行为。
- 必须包含的信息点。
- 禁止出现的幻觉点。
- 引用要求。
- 最大成本和最大耗时。

评测指标：

- 任务完成率。
- 事实准确率。
- 引用命中率。
- 幻觉率。
- 平均延迟。
- 平均成本。
- 审查通过率。

验收标准：

- 每次改动 Agent 节点、Prompt、检索策略后自动跑回归评测。
- 质量下降超过阈值时阻止发布。

### 9.3 人工反馈闭环

开发内容：

- 用户可对报告点赞、点踩、标记错误。
- 用户可标记“引用不准确”“内容空泛”“没有回答问题”“格式不好”。
- 反馈进入评测数据池。
- 管理后台可查看低分案例并复盘。

验收标准：

- 反馈能关联到会话、节点 Trace、Prompt 版本、模型版本。

## 10. 第六阶段：可观测性与运维

目标：线上问题能被发现、定位和修复。

### 10.1 结构化日志

开发内容：

- 使用 JSON 日志。
- 每条日志包含 `request_id`、`tenant_id`、`user_id`、`session_id`、`turn_id`、`node_name`。
- 敏感字段脱敏。
- 替换核心路径中的散落 `print`。

验收标准：

- 可以按一次请求追踪完整执行过程。
- 日志不会泄露 API Key、用户原文档敏感片段。

### 10.2 指标监控

核心指标：

- API QPS、错误率、延迟。
- SSE 连接数和断开率。
- Agent 每节点耗时和失败率。
- LLM 调用次数、Token、费用、失败率。
- 检索耗时、召回数量、空召回率。
- 文档解析成功率和平均耗时。
- Redis、向量库、数据库连接状态。

验收标准：

- 有 Grafana 或同类看板。
- 错误率、延迟、模型失败率超过阈值时告警。

### 10.3 链路追踪

开发内容：

- 引入 OpenTelemetry。
- 一次 `/chat` 请求形成完整 Trace。
- 每个 Agent 节点、检索、LLM、工具调用都是 Span。
- Trace 中记录 Prompt 版本、模型名、Token，但不记录完整敏感内容。

验收标准：

- 能快速定位一次慢请求卡在哪个节点。

## 11. 第七阶段：产品化能力

目标：让系统从技术 Demo 变成企业用户愿意长期使用的产品。

### 11.1 企业工作台

建议页面：

- 首页：最近任务、常用知识库、团队动态、用量概览。
- 研究工作台：聊天、流程状态、引用面板、历史脉络。
- 知识库管理：文档上传、解析状态、权限、版本。
- 报告资产库：收藏、标签、搜索、导出、分享。
- 任务中心：长任务进度、失败重试、定时任务。
- 管理后台：成员、角色、审计、模型配置、成本看板。

验收标准：

- 企业用户可以围绕知识库和报告资产持续工作，而不只是一次性聊天。

### 11.2 报告导出与协作

开发内容：

- 支持 Markdown、PDF、DOCX 导出。
- 支持报告版本历史。
- 支持评论、批注、段落级重新生成。
- 支持分享链接和访问权限。

验收标准：

- 报告从生成到审阅、修改、导出形成闭环。

### 11.3 模板化任务

开发内容：

- 内置调研模板：竞品分析、行业报告、论文综述、政策解读、技术选型。
- 每个模板绑定专用工作流、Prompt、输出结构。
- 支持企业自定义模板。

验收标准：

- 用户不需要每次从空白输入开始。
- 输出格式更稳定。

## 12. 第八阶段：部署与交付

目标：支持标准化交付和持续发布。

### 12.1 容器化

开发内容：

- 增加后端 Dockerfile。
- 增加前端 Dockerfile。
- 增加 `docker-compose.yml`，包含 API、Web、Redis、向量库、数据库。
- 将开发环境和生产环境配置分离。

验收标准：

- 新开发者可以一条命令启动完整依赖。
- 生产镜像不包含测试密钥和本地缓存。

### 12.2 数据库与迁移

建议引入 PostgreSQL 存储结构化数据：

- 用户、租户、角色。
- 知识库、文档、任务。
- 会话元数据、报告资产。
- 审计日志。

Redis 保留：

- 热会话缓存。
- SSE 状态。
- 短期任务状态。
- 分布式锁。

对象存储保留：

- 原始上传文件。
- 解析后的中间产物。
- 导出的报告文件。

验收标准：

- 使用 Alembic 或同类工具管理 schema migration。
- 数据可以备份和恢复。

### 12.3 CI/CD

流水线建议：

```text
Lint
  -> Unit Tests
  -> Integration Tests
  -> Frontend Build
  -> Docker Build
  -> Security Scan
  -> Deploy to Staging
  -> Agent Eval Smoke Test
  -> Manual Approval
  -> Deploy to Production
```

验收标准：

- 主分支始终可部署。
- 发布失败可以回滚到上一版本。

## 13. 数据治理与合规

开发内容：

- 数据分类：普通数据、企业敏感数据、个人信息、密钥。
- 数据保留策略：会话、上传文档、报告、日志分别设置保留期限。
- 支持用户删除会话和文档。
- 支持租户级数据导出。
- Prompt 和日志中避免长期保存敏感原文。
- 训练隔离声明：用户数据默认不进入模型训练。

验收标准：

- 可以回答“谁在什么时候访问了哪个文档并生成了什么报告”。
- 可以按租户删除或导出数据。

## 14. 性能与扩展性

开发内容：

- 将长任务从 HTTP 请求中拆出，使用任务队列。
- SSE 只负责订阅任务状态。
- 文档解析和索引异步化。
- 大文档分片处理，支持断点续跑。
- Agent 节点支持并发检索和并发工具调用。
- 对高频检索和历史摘要增加缓存。

验收标准：

- 多用户并发时不会互相阻塞。
- 大文档上传不会阻塞聊天主流程。
- 单租户可设置并发上限。

## 15. 推荐实施路线

### Milestone 1：企业级工程底座，2 到 3 周

目标：

- 配置管理。
- 统一错误处理。
- 结构化日志。
- 基础测试框架。
- Docker Compose 本地环境。
- API v1 目录拆分。

交付物：

- 可稳定本地启动的全依赖环境。
- 核心 API 单元测试和集成测试。
- 标准错误码和请求 ID。

### Milestone 2：安全与多租户，3 到 4 周

目标：

- 用户登录。
- JWT 鉴权。
- RBAC。
- tenant_id 数据隔离。
- 上传安全。
- 审计日志。

交付物：

- 企业内测可用的权限体系。
- 越权访问测试。
- 审计查询接口。

### Milestone 3：知识库平台，4 到 6 周

目标：

- 多知识库。
- 文档生命周期管理。
- 增量索引。
- 引用溯源。
- 检索质量评测。

交付物：

- 团队知识库管理后台。
- 报告引用可点击追溯。
- 检索评测集和指标。

### Milestone 4：Agent 质量与可观测性，4 到 6 周

目标：

- Workflow 版本管理。
- Prompt 版本管理。
- Model Gateway。
- Agent Eval。
- OpenTelemetry Trace。
- 成本看板。

交付物：

- Agent 改动可回归评测。
- 每次任务可追踪和复盘。
- 成本、延迟、失败率可视化。

### Milestone 5：产品化工作台，4 到 8 周

目标：

- 企业工作台。
- 报告资产库。
- 导出 PDF/DOCX。
- 模板化任务。
- 团队协作和分享。

交付物：

- 面向真实团队使用的产品闭环。
- 支持从知识库到报告资产的完整流程。

## 16. P0 开发 Backlog

建议优先排期以下任务：

| 编号 | 任务 | 说明 |
|---|---|---|
| P0-01 | 增加统一配置模块 | 消除散落环境变量读取 |
| P0-02 | 增加全局错误处理 | 统一 API 和 SSE 错误结构 |
| P0-03 | 增加请求 ID | 贯穿日志、SSE、Agent Trace |
| P0-04 | 替换关键 print 为结构化日志 | 保留调试信息但可检索 |
| P0-05 | 增加后端测试框架 | pytest、httpx、异步测试 |
| P0-06 | 增加 Agent 路由测试 | Router、Reviewer 回环、Researcher 停止逻辑 |
| P0-07 | 增加上传安全校验 | 文件名、类型、大小、路径安全 |
| P0-08 | 拆分 API routes | chat、sessions、knowledge 分文件 |
| P0-09 | 增加 Docker Compose | Redis、API、前端一键启动 |
| P0-10 | 定义标准领域模型 | Session、Turn、Document、KnowledgeBase |

## 17. 关键技术决策建议

### 17.1 数据存储

建议组合：

- PostgreSQL：结构化业务数据。
- Redis：热会话、缓存、短任务状态。
- 向量数据库：知识库索引。
- 对象存储：原始文档和导出文件。

不要把所有东西都放 Redis。Redis 适合快，但不适合作为企业级长期主存储。

### 17.2 Agent 架构

保留当前 Supervisor-style 中心调度范式，但主引擎以纯 Python Workflow Engine 承载，LangGraph 只作为 legacy fallback。继续增加：

- Workflow Registry。
- Prompt Registry。
- Tool Registry。
- Model Gateway。
- Evaluation Hooks。
- Trace Hooks。

不建议直接改成 Swarm。当前场景是企业调研和报告生成，更需要可控、可审计、可复现，而不是 Agent 自由传球。

### 17.3 前端定位

前端不要只做聊天框，应升级为“研究工作台”：

- 左侧：会话与报告资产。
- 中间：当前研究任务与报告。
- 右侧：流程状态、引用来源、历史脉络、成本信息。
- 管理区：知识库、成员、权限、审计、模型配置。

## 18. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| LLM 输出不可控 | 报告质量波动 | Agent Eval、Reviewer 强化、引用约束 |
| 检索召回不足 | 答案空泛或幻觉 | Hybrid Retrieval、Reranker、评测集 |
| 多租户隔离不彻底 | 数据泄露 | tenant_id 强校验、越权测试 |
| 成本不可控 | 企业使用费用失控 | Model Gateway、预算、限流、看板 |
| 长任务阻塞 | 并发能力差 | 任务队列、异步索引、SSE 订阅 |
| Prompt 难以维护 | 迭代不可控 | Prompt 版本管理和回归测试 |
| 日志泄露敏感内容 | 合规风险 | 脱敏、采样、最小化保存 |

## 19. 企业级完成定义

当系统满足以下条件时，可以认为进入企业级可交付阶段：

- 有认证、授权、多租户和审计。
- 知识库支持多团队、多文档、增量索引和引用溯源。
- Agent 执行可追踪、可回放、可评测、可灰度。
- 关键 API 有自动化测试和稳定错误码。
- 部署有 Docker、CI/CD、环境隔离和回滚机制。
- 线上有日志、指标、Trace、告警和成本看板。
- 用户能完成从上传知识、发起研究、审阅报告、协作修改到导出的完整流程。

## 20. 下一步建议

最建议先做 Milestone 1。原因是当前项目已经有不错的 Agent 能力，但工程底座还偏原型。如果直接继续堆 Agent 功能，后面会遇到难以调试、难以测试、难以部署、难以多人协作的问题。

第一批可以先开这 5 个开发分支：

- `codex/config-and-errors`：配置管理和统一错误处理。
- `codex/structured-logging`：请求 ID 和结构化日志。
- `codex/backend-tests`：pytest 测试框架和核心路由测试。
- `codex/upload-security`：文件上传安全和文档生命周期雏形。
- `codex/docker-compose-dev`：本地一键启动环境。

完成这批后，再进入认证、多租户和知识库平台化，会更稳。
