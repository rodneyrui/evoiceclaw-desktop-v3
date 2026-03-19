# eVoiceClaw Desktop v3 — 代码索引 (CODEBASE_INDEX)

> 最后更新: 2026-03-19
> 状态: V3.4 SmartRouter 语义向量路由（bge-small kNN 优先 → LLM 降级）+ Multi-Agent 协作基础设施 + 深度思考双验证
> 用途: 动态维护文件-职责映射，每次新增/修改/删除文件时同步更新

---

## 项目根目录

| 文件 | 职责 | 状态 |
|------|------|------|
| `ARCHITECTURE.md` | AI OS 完整架构设计 v1.1 | ✅ 已创建 |
| `.gitignore` | Git 忽略规则（data/, secrets.yaml, node_modules/ 等） | ✅ 已创建 |
| `README.md` | 项目说明 | ⏳ 待创建 |

---

## docs/ — 项目文档

| 文件 | 职责 | 状态 |
|------|------|------|
| `docs/BACKLOG.md` | 开发进度追踪（Phase 0-5 + 路线图 R1-R5） | ✅ 已创建 |
| `docs/CODEBASE_INDEX.md` | 本文件 | ✅ 已创建 |
| `docs/PRIVACY_PIPELINE.md` | 隐私管道详细设计（5级管道数据流+模块详解+配置参考） | ✅ 已创建 |
| `docs/SHELL_SANDBOX.md` | Shell 沙箱三层防护架构（白名单表+危险模式+运行时沙箱） | ✅ 已创建 |
| `docs/GATEKEEPER.md` | 守门员集成文档（审查流程+数据模型+Skill生命周期） | ✅ 已创建 |
| `docs/MIGRATION_FROM_V2.md` | v2 组件迁移指南 | ⏳ 待创建 |

---

## backend/app/ — 后端应用

### 入口

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `main.py` | FastAPI 入口 + 生命周期管理（SQLite/LanceDB 初始化+关闭） | ✅ 已创建 | 重构自 v2 `main.py` |

### api/v1/ — REST API 路由层

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `api/deps.py` | API 依赖注入（get_config） | ✅ 已创建 | 新建 |
| `api/v1/chat.py` | POST /chat (SSE 流式) + GET /chat/models | ✅ 已创建 | 迁移自 v2 `api/v1/chat.py` |
| `api/v1/config.py` | GET/PUT /config（api_key 脱敏）+ GET/PUT /secrets | ✅ 已创建 | 迁移自 v2 `api/v1/config.py` |
| `api/v1/skills.py` | Skill CRUD（列表/安装/更新/详情/卸载） | ✅ 已创建 | 迁移自 v2 `api/v1/skills.py` |
| `api/v1/audit.py` | GET /audit（组件/级别/trace_id 过滤） | ✅ 已创建 | 新建 |
| `api/v1/memory.py` | 记忆 CRUD + 语义召回 | ⏳ 待创建 | 迁移自 v2 `api/v1/memory.py` |
| `api/v1/workspace.py` | 工作区管理 | ⏳ 待创建 | 迁移自 v2 `api/v1/workspace.py` |
| `api/v1/auth.py` | 认证 | ⏳ 待创建 | 迁移自 v2 `api/v1/auth.py` |
| `api/v1/system.py` | 健康检查 /system/health | ✅ 已创建 | 新建 |

### kernel/ — LLM 内核

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `kernel/router/smart_router.py` | 快速路径 → kNN 向量预测优先（~30ms）→ LLM 分类器降级 → 模型选择（12 能力 + 3 规格需求维度） | ✅ 已更新 | 重构自 v2 `services/smart_router.py` |
| `kernel/router/knn_predictor.py` | kNN 需求向量预测器：bge-small 编码 + 2026 条 R1 标注锚点 + top-5 加权回归 + .npy 缓存 + 置信度分流（std>1.42 降级 LLM） | ✅ 已创建 | 新建（2026-03-17） |
| `kernel/router/llm_router.py` | API/CLI 通道分派 + fallback 降级 + collect_stream_text | ✅ 已创建 | 迁移自 v2 `services/llm/llm_router.py` |
| `kernel/router/model_matrix.py` | 15 维需求向量评分矩阵（12 能力 + 3 规格需求，动态权重替代硬编码成本惩罚）+ 协作 bonus（parallel_tool_calls 模型在高 agent_tool_use 需求时获 15% 加分） | ✅ 已更新 | 精简自 v2 `infrastructure/model_matrix.py` |
| `kernel/router/policy_engine.py` | PolicyEngine 硬性约束筛选（exclude_providers/exclude_models/require_tool_support + 全部排除安全回退）；config.yaml `policy_rules` 加载；全局单例 | ✅ 已创建 | 新建（2026-03-18） |
| `kernel/providers/api_provider.py` | LiteLLM 统一接口 + provider 映射内联 + tool_calls 累积 | ✅ 已创建 | 迁移自 v2 `services/llm/api_provider.py` |
| `kernel/providers/cli_provider.py` | Claude Code CLI stream-json 包装器 | ✅ 已创建 | 迁移自 v2 `services/llm/cli_agent_provider.py` |
| `kernel/providers/health.py` | Provider 健康追踪 + R5 jitter | ✅ 已创建 | 迁移自 v2 `infrastructure/provider_health.py` |
| `kernel/tools/registry.py` | ToolRegistry 中心注册表 + 模型工具过滤 | ✅ 已创建 | 迁移自 v2 `services/skill/tool_registry.py` |
| `kernel/tools/executor.py` | ToolExecutor 执行引擎 + R4 基础 schema 校验 + 权限检查（跳过时 debug 日志）+ workspace_id 注入（_context 字段）+ 审计日志（TOOL_EXECUTED 含 workspace_id/PERMISSION_DENIED/TIMEOUT/ERROR） | ✅ 已创建 | 迁移自 v2 `services/skill/tool_executor.py` |
| `kernel/tools/protocol.py` | SkillProtocol 抽象基类 + tool_timeout + required_permissions + security_level | ✅ 已创建 | 迁移自 v2 `services/skill/protocol.py` |
| `kernel/context.py` | ExecutionContext 不可变数据类（depth/max_depth/token_budget/tokens_used/trace_id/parent_model_id）+ ContextVar + `get_or_create_context()`；Multi-Agent 递归保护基础设施 | ✅ 已创建 | 新建（2026-03-18） |

### kernel/tools/builtin/ — 内置硬工具

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `builtin/network.py` | HttpRequestTool（SSRF 防护 + 50KB 截断 + NetworkGuard 域名白名单）+ `_is_private_host` 公共函数 | ✅ 已创建 | 迁移自 v2 `http_request.py` |
| `builtin/web_search.py` | WebSearchTool（博查优先 + DuckDuckGo 降级） | ✅ 已创建 | 迁移自 v2 `web_search.py` |
| `builtin/web_fetch.py` | WebFetchTool（trafilatura 提取 + 正则降级 + NetworkGuard 域名白名单） | ✅ 已创建 | 迁移自 v2 `web_fetch.py` |
| `builtin/filesystem.py` | ReadFileTool, ListDirectoryTool, WriteFileTool, EditFileTool（统一 `_is_safe_path` 路径安全校验: 黑名单+白名单双重检查 + 工作区集成 + required_permissions 声明） | ✅ 已创建 | 迁移自 v2 `filesystem.py` |
| `builtin/database.py` | QueryDatabaseTool（SELECT-only + 强制 LIMIT） | ✅ 已创建 | 迁移自 v2 `query_database.py` |
| `builtin/memory_ops.py` | MemoryOpsTool（recall/save/delete，LanceDB 向量检索 + Embedding 集成 + workspace_id 隔离） | ✅ 已创建 | 新建 |
| `builtin/workspace.py` | WorkspaceMgmtTool（register/list/activate/info/tree/unregister + configure_shell/network/env/secret/list_secrets） | ✅ 已创建 | 新建 |
| `builtin/skill_mgmt.py` | SkillMgmtTool（list/install/uninstall/info，调用守门员审查） | ✅ 已创建 | 新建 |
| `builtin/code_review.py` | CodeReviewTool（读取源码 + 调用 LLM 审核，支持单文件/目录 + AI 审核标记 + 审计记录） | ✅ 已创建 | 新建 |
| `builtin/consult_expert.py` | ConsultExpertTool（专家咨询：递归保护 + 自咨询避免 + 路由选专家模型 + 子上下文传递 + 审计日志）；第 14 个内置工具 | ✅ 已创建 | 新建（2026-03-18） |
| `builtin/shell.py` | ExecCommandTool（受控 Shell，三层沙箱 + 审计日志 + Shell 安全级别 L1/L2/L3 + 启用检查） | ✅ 已创建 | Phase 3 新建 |
| `builtin/ai_marker.py` | AiMarkerTool（AI 内容标记，支持 code/document/review/commit 4 种类型，宪法第25条） | ✅ 已创建 | Phase 6 新建 |
| `builtin/browser.py` | browser_tool | ⏳ 待创建 | 需 Playwright |

### pipeline/ — 隐私管道

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `pipeline/pipeline.py` | 管道编排器（① → ③ → ②④并行 + trace_id + 阶段耗时 + 全局单例 + workspace_id 传递） | ✅ 已创建 | 新建 |
| `pipeline/cognitive_isolator.py` | ① 认知隔离器 V2（多级检测引擎: Level 0 文档类型语义 + Level 1 正则 + Level 2 AC自动机 + Level 3 实体回查 + Level 4 NER兜底 + 置信度上下文调整 + 向量反向匹配 + 动态积累 + SessionPrivacyContext） | ✅ 已创建 | 新建 |
| `pipeline/doc_type_detector.py` | Level 0 文档类型语义检测器（YAML 模板加载 + 关键词触发 + 向量反向匹配 + 文件名人名提取 + 模板敏感字段搜索） | ✅ 已创建 | 新建 |
| `pipeline/ner_detector.py` | Level 4 NER 兜底检测器（jieba.posseg 中文分词词性标注 + 人名识别 + 置信度 0.65） | ✅ 已创建 | 新建 |
| `pipeline/ac_dict_detector.py` | Level 2 AC 自动机敏感词检测器（pyahocorasick + 动态添加/重建 + O(n) 多模式匹配） | ✅ 已创建 | 新建 |
| `pipeline/entity_lookback.py` | Level 3 LanceDB 实体回查检测器（异步查询 PERSON 类型实体 + 文本匹配） | ✅ 已创建 | 新建 |
| `pipeline/entity_mapper.py` | ② 实体映射器（称谓/引用模式检测 + LanceDB 持久化 + 去重 + workspace_id 隔离） | ✅ 已创建 | 新建 |
| `pipeline/context_compressor.py` | ③ 动态上下文压缩器（token 预算 + 中/英估算 + 按逻辑块截断保护 tool_calls+tool 消息对） | ✅ 已创建 | 新建 |
| `pipeline/memory_injector.py` | ④ 三层渐进式记忆注入器（L1/L2/L3 并行检索 + R1 reranker 预留 + workspace_id 过滤） | ✅ 已创建 | 新建 |
| `pipeline/memory_distiller.py` | ⑤ 记忆蒸馏器（LLM 结构化抽取 → memories/distilled 双表 + workspace_id 写入） | ✅ 已创建 | 新建 |
| `pipeline/privacy_restorer.py` | 隐私恢复器（UUID→原始数据替换 + 残留检测 + 一致性检查） | ✅ 已创建 | 新建 |

### memory/ — 分层语义记忆系统

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `memory/store.py` | 记忆存储引擎（LanceDB + SQLite） | ⏳ 待创建 | 重构自 v2 `memory/memory_store.py` |
| `memory/semantic_search.py` | 向量语义检索 | ⏳ 待创建 | 新建 |
| `memory/auto_extractor.py` | LLM 自动抽取记忆 | ⏳ 待创建 | 迁移自 v2 `memory/auto_extractor.py` |
| `memory/journal.py` | 对话日志持久化 | ⏳ 待创建 | 迁移自 v2 `memory/journal_service.py` |
| `memory/models.py` | Memory 数据模型 | ⏳ 待创建 | 重构 |

### security/ — 安全层

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `security/gatekeeper/gatekeeper.py` | Gatekeeper 主逻辑（调用审查 LLM + JSON 解析） | ✅ 已创建 | 新建 |
| `security/gatekeeper/prompt.py` | V5 System Prompt 存储（yaml加载+内置默认） | ✅ 已创建 | 新建 |
| `security/gatekeeper/models.py` | ReviewResult, ActionDeclaration, SkillMeta(+authorization_mode), AuthorizationMode 枚举 | ✅ 已创建 | 新建 |
| `security/shell_sandbox.py` | Shell 三层沙箱（白名单+Skill声明+运行时ulimit）+ Shell 安全级别 L1/L2/L3 + get_shell_config/check_shell_enabled + 工作区环境变量合并 | ✅ 已创建 | 新建 |
| `security/audit.py` | 审计日志（trace_id 全链路 + audit.db 写入 + 查询 + workspace_id 过滤） | ✅ 已创建 | 新建 |
| `security/network_guard.py` | NetworkGuard 域名白名单守卫（工作区级白名单 + 内网IP拦截 + 云元数据拦截 + 子域匹配） | ✅ 已创建 | Phase 6 新建 |
| `security/rate_limiter.py` | API 速率限制中间件（滑动窗口算法，按 IP+路径分组，chat 10次/分、GET 2x 放宽） | ✅ 已创建 | SA-7 安全审计修复 |
| `security/intent_analyzer.py` | 意图安全分析 | ⏳ 待创建 | 迁移自 v2 `security/intent_analyzer.py` |

### services/ — 业务服务层

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `services/chat_service.py` | 对话引擎（流式 + 工具循环 + 隐私管道集成 + workspace_id 传递 + privacy.strict_mode 脱敏拒绝 + auto 模式 stream_with_fallback 降级 + URL预处理 + 过期蒸馏 + 14个内置工具注册 + 回复验证集成） | ✅ 已创建 | 重构自 v2 `services/chat_service.py` |
| `services/skill_service.py` | Skill 生命周期管理（安装+更新+卸载+版本+ACTIONS + authorization_mode 授权模式） | ✅ 已创建 | 重构 |
| `services/workspace_service.py` | 工作区管理（注册/激活/注销/文件树 + 全局单例 + JSON 元数据持久化 + shell/network/env 配置 + 工作区级 secrets.json 加密存储） | ✅ 已创建 | 新建 |
| `services/verification_service.py` | 回复验证服务（确定性规则触发 + 四层验证: legacy/强模型交叉/搜索验证/深度思考双模型 + 自动修正 + 模型能力画像驱动审核模型选择）；`_verify_by_deep_think()` 并行调用 DeepSeek R1 + Kimi K2 Thinking（consult_expert ≥2 次触发，asyncio.gather + 300s 超时，任一发现问题即不通过）；`has_multiple_api_providers()` 单 Provider 禁用守卫；领域知识从 `data/generated_rules/verification_config.yaml` 动态加载，未生成时英文 Prompt 降级；`_set_verification_config_for_testing()` 供测试注入 | ✅ 已更新 | 迁移自 v2 `services/verification/verification_service.py` |
| `services/soul_service.py` | 人格系统 | ⏳ 待创建 | 迁移自 v2（简化） |
| `services/quota_service.py` | 额度管理 | ⏳ 待创建 | 迁移自 v2 |

### infrastructure/ — 基础设施

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `infrastructure/db.py` | SQLite 连接管理 + 表初始化（sessions/messages/audit_log + workspace_id 列 + ALTER TABLE 兼容） | ✅ 已创建 | 迁移自 v2 |
| `infrastructure/vector_db.py` | LanceDB 连接管理 + 3 表初始化（含 workspace_id 字段）+ 表实例缓存（避免重复 open_table） | ✅ 已创建 | 新建 |
| `infrastructure/embedding.py` | Embedding 服务（API/本地双模式 + LRU 缓存 256 条 + CacheStats 监控） | ✅ 已创建 | 新建 |
| `infrastructure/sse.py` | SSE 流式推送（asyncio.Queue 事件队列） | ✅ 已创建 | 迁移自 v2 |
| `infrastructure/sandbox.py` | 脚本执行沙箱 | ⏳ 待创建 | 迁移自 v2 |
| `infrastructure/usage_repo.py` | API 使用量统计 | ⏳ 待创建 | 迁移自 v2 |

### core/ — 核心配置

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `core/config.py` | YAML 配置 + Secrets 分离 + 环境变量替换 | ✅ 已创建 | 迁移自 v2 |
| `core/security.py` | JWT 认证（预留 user_id 提取） | ⏳ 待创建 | 迁移自 v2 |

### domain/ — 领域模型

| 文件 | 职责 | 状态 | v2 来源 |
|------|------|------|---------|
| `domain/models.py` | ChatMessage, StreamChunk, ToolCall, RedactionEntry（预留 user_id） | ✅ 已创建 | 迁移自 v2 `services/llm/models.py` |
| `domain/events.py` | 系统事件定义（EventType 枚举 + SystemEvent） | ✅ 已创建 | 新建 |

---

## frontend/src/ — 前端应用

### 入口与配置

| 文件 | 职责 | 状态 |
|------|------|------|
| `main.tsx` | React 根挂载 + i18n 初始化 | ✅ 已创建 |
| `App.tsx` | 根组件（Providers + Routes） | ✅ 已创建 |
| `index.css` | Tailwind 4 主题（light/dark CSS 变量 + glass 工具类） | ✅ 已创建 |
| `vite-env.d.ts` | Vite 类型声明 | ✅ 已创建 |

### app/ — 应用骨架

| 文件 | 职责 | 状态 |
|------|------|------|
| `app/routes.tsx` | 路由定义（Layout + 6 页面全部 lazy-loaded） | ✅ 已创建 |
| `app/providers.tsx` | QueryClient + BrowserRouter + Toaster 全局 Provider | ✅ 已创建 |

### lib/ — 工具库

| 文件 | 职责 | 状态 |
|------|------|------|
| `lib/utils.ts` | cn() 样式合并（clsx + tailwind-merge） | ✅ 已创建 |

### i18n/ — 国际化

| 文件 | 职责 | 状态 |
|------|------|------|
| `i18n/index.ts` | i18next 初始化 + localStorage 语言持久化 | ✅ 已创建 |
| `i18n/locales/zh-CN.json` | 中文翻译 | ✅ 已创建 |
| `i18n/locales/en-US.json` | 英文翻译 | ✅ 已创建 |

### shared/ — 共享层

| 文件 | 职责 | 状态 |
|------|------|------|
| `shared/api/client.ts` | HTTP 客户端（apiFetch/apiGet/apiPost，无鉴权） | ✅ 已创建 |
| `shared/hooks/useTheme.ts` | 主题管理（light/dark/system + localStorage） | ✅ 已创建 |
| `shared/components/Layout.tsx` | 全局侧边栏布局（6 个导航项 + 语言/主题切换） | ✅ 已创建 |

### features/ — 功能模块

| 文件 | 职责 | 状态 |
|------|------|------|
| `features/chat/directChatApi.ts` | SSE 流式 API（streamChat 生成器 + getAvailableModels） | ✅ 已创建 |
| `features/chat/useDirectChat.ts` | 对话状态 Hook（消息排队 + localStorage 持久化 + URL 检测） | ✅ 已创建 |
| `features/chat/ChatPage.tsx` | 对话页面（ModelSelector + MessageList + InputArea） | ✅ 已创建 |
| `features/skills/SkillsPage.tsx` | Skill 管理页面（列表+安装+卸载+状态+actions展开） | ✅ 已创建 |
| `features/memory/MemoryPage.tsx` | 记忆管理占位页面 | ✅ 已创建 |
| `features/workspace/WorkspacePage.tsx` | 工作区管理占位页面 | ✅ 已创建 |
| `features/settings/SettingsPage.tsx` | 系统设置（Provider/API Key/隐私 三 Tab） | ✅ 已创建 |
| `features/audit/AuditPage.tsx` | 审计日志查看（过滤+表格） | ✅ 已创建 |

### components/ — UI 组件

| 文件 | 职责 | 状态 |
|------|------|------|
| `components/chat/MessageList.tsx` | 虚拟滚动消息列表（Virtuoso + Markdown 渲染 + 代码块复制 + 下载） | ✅ 已创建 |
| `components/chat/InputArea.tsx` | 输入框（IME 兼容 + sessionStorage 草稿 + Enter 发送） | ✅ 已创建 |
| `components/chat/ModelSelector.tsx` | 模型选择器（按 Provider 分组 + 自动选择） | ✅ 已创建 |
| `components/ui/skeleton.tsx` | 加载骨架屏组件 | ✅ 已创建 |

---

## data/ — 运行时数据 (.gitignore)

| 目录 | 用途 |
|------|------|
| `data/vectors/entities/` | LanceDB 实体类别映射向量 |
| `data/vectors/memories/` | LanceDB 记忆向量 |
| `data/vectors/distilled/` | LanceDB 蒸馏记忆向量 |
| `data/db/main.db` | SQLite 主库（会话、任务、用户） |
| `data/db/audit.db` | SQLite 审计库（独立，支持轮转） |
| `data/skills/` | 已安装 Skill 目录 |
| `data/workspaces/` | 工作区数据 |
| `data/journals/` | 对话日志 |
| `data/configs/zh/doc_type_templates.yaml` | 中文文档类型模板（10 种: 征信报告/合同/借条/病历/简历/发票/银行流水/房产证/身份证/保险单） |
| `data/configs/en/doc_type_templates.yaml` | 英文文档类型模板（6 种: credit_report/contract/medical_record/resume/bank_statement/tax_return） |
| `data/preset/preset_evaluations.json` | 模型预置画像数据（18 个模型 × 12 维度评分 + 成本 + 上下文窗口 + parallel_tool_calls 行为特性标注） |
| `data/preset/preset_common_sense.json` | 通用常识记忆数据（30 条，7 类） |
| `data/preset/intent_anchors.jsonl` | kNN 需求向量预测锚点数据（2026 条 R1 标注，15 维 0-10，从 Cerebellum train.jsonl 复制） |
| `data/preset/default_rules/` | 预置默认规则（4 个 YAML），首次安装时复制到 `data/generated_rules/`，开源用户无需推理模型即可使用 |

---

## backend/tests/ — 安全测试

| 文件 | 职责 | 状态 |
|------|------|------|
| `tests/__init__.py` | 测试包标识 | ✅ 已创建 |
| `tests/conftest.py` | 测试配置（Python 路径设置） | ✅ 已创建 |
| `tests/test_shell_sandbox.py` | Shell 沙箱安全测试（85+ 用例: 白名单/黑名单/curl写操作/危险模式/Skill声明/运行时沙箱） | ✅ 已创建 |
| `tests/test_privacy_pipeline.py` | 隐私管道测试（28 用例: 认知隔离器/隐私恢复器/泄露防护/上下文压缩器） | ✅ 已创建 |
| `tests/test_doc_type_detector.py` | Level 0 文档类型检测测试（24 用例: 触发匹配/模板提取/文件名人名/隔离器集成/隐私提醒） | ✅ 已创建 |
| `tests/test_ac_dict_and_lookback.py` | AC 自动机 + 实体回查测试（11 用例: 基本检测/动态重建/位置验证/隔离器集成/动态积累） | ✅ 已创建 |
| `tests/test_gatekeeper.py` | 守门员测试（16 用例: prompt加载/JSON解析/数据模型/恶意Skill模式） | ✅ 已创建 |
| `tests/test_execution_context.py` | ExecutionContext 单元测试（16 用例: 默认值/递归保护/budget/child/ContextVar 隔离） | ✅ 已创建 |
| `tests/test_consult_expert.py` | consult_expert 工具测试（14 用例: 递归拒绝/自咨询避免/正常调用/异常/上下文恢复） | ✅ 已创建 |
| `tests/test_policy_engine.py` | PolicyEngine 测试（14 用例: exclude_providers/exclude_models/全部排除回退/config 加载/单例） | ✅ 已创建 |
| `tests/test_verification_service.py` | 回复验证服务测试（34 用例: 触发规则 8 场景 + 高风险声称 + 事实提取 + 数据模型 + 审核模型降级 + consult_expert 触发/阈值/降级/外部工具优先 + 深度思考不可用降级） | ✅ 已更新 |

---

## deploy/ — 部署

| 文件 | 职责 | 状态 |
|------|------|------|
| `deploy/deploy-remote.sh` | 远程部署脚本（rsync+systemd/nohup+健康检查, 支持 --backend-only/--frontend-only/--dry-run） | ✅ 已创建 |
| `deploy/deploy-macbook.sh` | MacBook Pro 远程部署脚本（nohup 管理服务，Python 版本自动检测，支持 --compile-rules Cython 编译） | ✅ 已更新 |
| `deploy/evoiceclaw-desktop-v3.service` | systemd 服务单元文件（自动重启+安全加固+日志输出到 journal） | ✅ 已创建 |
| `deploy/compile_rules.py` | Cython 编译脚本（evaluation/rules/ 6 个 .py→.so/.pyd，排除 r1_prompt.py，支持 --clean/--verify） | ✅ 已创建 |

---

## .github/workflows/ — CI/CD

| 文件 | 职责 | 状态 |
|------|------|------|
| `.github/workflows/build-rules.yml` | 三平台 Cython 编译矩阵（Linux x86_64 / macOS arm64 / Windows x86_64），rules/ 推送或手动触发 | ✅ 已创建 |

---

## 配置文件

| 文件 | 用途 | 版本控制 |
|------|------|---------|
| `backend/config.yaml` | 非敏感配置（LLM/Provider/Embedding/隐私/Shell/审计） | ✅ 已创建 |
| `backend/secrets.yaml` | API Key 等敏感数据（模板） | ✅ 已创建 |
| `backend/config.example.cn.yaml` | 中国区配置模板（DeepSeek+智谱+通义+Kimi+百川+BGE embedding） | ✅ 已创建 |
| `backend/config.example.us.yaml` | 国际区配置模板（OpenAI+Anthropic+Google+OpenAI embedding） | ✅ 已创建 |
| `backend/config.example.local.yaml` | 本地模型配置模板（Ollama+BGE embedding） | ✅ 已创建 |
| `backend/secrets.yaml.example` | API Key 占位模板（所有 Provider） | ✅ 已创建 |
| `LICENSE` | Apache License 2.0 | ✅ 已创建 |
| `docs/DEVELOPMENT_PLAN.md` | 开发计划（Phase 2-5 + 开源准备 + 自举验证） | ✅ 已创建 |
| `backend/requirements.txt` | Python 依赖 | ✅ 已创建 |
| `backend/pyproject.toml` | 项目元数据 | ✅ 已创建 |
| `frontend/package.json` | 前端依赖 | ✅ 已创建 |
| `frontend/vite.config.ts` | Vite 构建配置（代理+别名） | ✅ 已创建 |
| `frontend/tsconfig.json` | TypeScript 配置 | ✅ 已创建 |

---

## 变更记录

| 日期 | 变更内容 |
|------|---------|
| 2026-03-09 | 初始创建，基于 ARCHITECTURE.md v1.1 列出所有计划文件 |
| 2026-03-09 | Phase 0 完成: main.py, config.py, db.py, vector_db.py, models.py, events.py, system.py, 前端骨架(App/routes/providers/client), config.yaml, secrets.yaml |
| 2026-03-09 | Phase 1 LLM 内核: protocol.py, registry.py, executor.py, health.py, api_provider.py, cli_provider.py, model_matrix.py, llm_router.py, smart_router.py, sse.py, chat_service.py, chat.py, deps.py; models.py 新增 provider/usage/reasoning_content/name 字段; main.py 串联内核初始化 |
| 2026-03-09 | Phase 1 内置工具: builtin/network.py, builtin/web_search.py, builtin/web_fetch.py, builtin/filesystem.py, builtin/database.py; chat_service.py 更新注册 7 个工具 |
| 2026-03-09 | 开源基础设施: config.example.cn/us/local.yaml, secrets.yaml.example, LICENSE(Apache 2.0), docs/DEVELOPMENT_PLAN.md |
| 2026-03-09 | Phase 2 隐私管道: pipeline/(cognitive_isolator, entity_mapper, context_compressor, memory_injector, memory_distiller, privacy_restorer, pipeline).py; infrastructure/embedding.py; chat_service.py 集成管道(输入隔离→记忆注入→流式恢复→过期蒸馏); main.py 新增 Pipeline+Embedding 初始化 |
| 2026-03-09 | Phase 3 安全层: security/audit.py(审计服务), security/shell_sandbox.py(三层沙箱), security/gatekeeper/(prompt+models+gatekeeper).py, kernel/tools/builtin/shell.py(ExecCommandTool), services/skill_service.py(Skill生命周期); main.py+chat_service.py 集成 |
| 2026-03-09 | Phase 4 核心对话界面: lib/utils.ts, i18n/(index+zh-CN+en-US), shared/(client+useTheme+Layout), features/chat/(directChatApi+useDirectChat+ChatPage), components/chat/(MessageList+InputArea+ModelSelector), components/ui/skeleton; app/(routes+providers)更新; 构建验证通过 |
| 2026-03-09 | Phase 4 剩余页面: 后端 api/v1/(skills+audit+config).py + main.py 路由注册; 前端 features/(skills/SkillsPage+audit/AuditPage+settings/SettingsPage+workspace/WorkspacePage+memory/MemoryPage); routes.tsx 全部 lazy-loaded; i18n 补全; 构建验证通过 |
| 2026-03-09 | Phase 5 完成: tests/(test_shell_sandbox+test_privacy_pipeline+test_gatekeeper).py 共129用例全部通过; 性能优化(embedding LRU缓存+LanceDB表缓存+记忆注入并行+管道②④并行); docs/(PRIVACY_PIPELINE+SHELL_SANDBOX+GATEKEEPER).md; deploy/(deploy-remote.sh+systemd.service) |
| 2026-03-09 | 新增 5 个内置工具: filesystem.py 新增 EditFileTool(精确编辑+工作区集成); memory_ops.py(recall/save/delete+向量检索); code_review.py(LLM代码审核); workspace.py(WorkspaceMgmtTool+WorkspaceService); skill_mgmt.py(SkillMgmtTool); chat_service.py 注册 13 个工具; main.py 初始化 WorkspaceService; filesystem.py 读写根目录集成激活工作区路径 |
| 2026-03-09 | Phase 6 逻辑层合规: 新建 security/network_guard.py(域名白名单+内网拦截+云元数据拦截); 新建 builtin/ai_marker.py(4种AI内容标记); protocol.py 新增 required_permissions/security_level; executor.py 新增权限检查+审计日志(4种事件); 所有11个内置工具补充权限声明; db.py audit_log 表新增 workspace_id; audit.py log_event/query_audit 支持 workspace_id; vector_db.py 3表 schema 新增 workspace_id; memory_ops/memory_injector/entity_mapper/memory_distiller/pipeline 全链路 workspace_id 隔离; shell_sandbox.py 新增 Shell 安全级别 L1/L2/L3+工作区环境变量合并; shell.py 新增启用检查; network.py/web_fetch.py 集成 NetworkGuard; workspace_service.py 扩展 Workspace+secrets 管理; workspace.py 新增 5 个 configure 操作; code_review.py 添加 AI 标记+审计; gatekeeper/models.py 新增 AuthorizationMode; skill_service.py 支持 authorization_mode; chat_service.py 注册 AiMarkerTool(14个工具); config.yaml 新增 network_guard+Shell 默认禁用 |
| 2026-03-11 | Phase 6.5 + 开源合规改造: 新建 services/verification_service.py(三层验证机制,领域知识从 verification_config.yaml 动态加载,_set_verification_config_for_testing() 测试注入,英文 Prompt 降级); evaluation/rules/prompt.py 新增 Section 5(verification_config.yaml 格式说明，更新输出格式为 5 文件); evaluation/rules/rule_generator.py 加入 verification_config.yaml(RULE_FILES/解析/可选校验); 代码注释清理(chat_service/memory_injector/pipeline/rule_generator 去除内部架构术语，保留 DeepSeek R1 产品名) |
| 2026-03-12 | 认知隔离器 V2 升级: cognitive_isolator.py 重构为多级检测引擎(Level 0~4); 新建 pipeline/doc_type_detector.py(文档类型语义检测+文件名人名提取+模板敏感字段搜索); 新建 pipeline/ac_dict_detector.py(AC自动机+动态积累); 新建 pipeline/entity_lookback.py(LanceDB实体回查); domain/models.py 新增 SessionPrivacyContext; chat_service.py 工具返回内容过隔离器+privacy_notice注入; data/configs/zh/en doc_type_templates.yaml(中英文文档类型模板); tests/test_doc_type_detector.py(24用例)+test_ac_dict_and_lookback.py(11用例); requirements.txt 新增 pyahocorasick; 71 个隐私管道测试全部通过 |
| 2026-03-12 | 逻辑层审计 6 项修复: chat_service.py 新增 _get_active_workspace_id()+workspace_id 传递给 pipeline/executor + privacy.strict_mode 脱敏拒绝开关 + auto 模式 stream_with_fallback 降级(导入 select_models_for_direct_chat); context_compressor.py 新增 _group_into_blocks() 按逻辑块截断(保护 tool_calls+tool 消息对); executor.py execute()/execute_all() 新增 workspace_id 参数+_context 注入+审计日志记录 workspace_id + _check_permissions() 跳过时 debug 日志 |
| 2026-03-12 | filesystem _is_safe_path 修复: filesystem.py 新增 `_is_safe_path()` 统一路径安全检查(黑名单+白名单); ReadFileTool/ListDirectoryTool 改用 _is_safe_path 替代 _is_blocked_read_path; WriteFileTool/EditFileTool 改用 _is_safe_path 替代 _is_safe_write_path; 修复 28 个测试失败，全量 833 测试通过 |
| 2026-03-12 | 工作区前端完整实现 + PDF OCR 修复 + model_alias 正则扩展: WorkspacePage.tsx 从占位页面升级为完整功能页面; zh-CN.json/en-US.json 补全 18 个 workspace.* key; pdf_reader.py 安全检查改用 _is_safe_path + OCR 分辨率 300 DPI + 扫描版诊断提示; requirements.txt rapidocr-onnxruntime 取消注释; model_alias.py 新增「让 R1 来，任务」和「让 R1，任务」两条正则模式，修复"让 R1 来"无法识别的问题 |
| 2026-03-19 | 协作 bonus：ModelProfile 新增 `parallel_tool_calls` 行为特性字段；`select_models_by_requirements()` 当 `agent_tool_use >= 7` 时给 `parallel_tool_calls=True` 的模型加 15% bonus；`preset_evaluations.json` 标注 MiniMax-M2.5 支持并行工具调用；审计日志新增 `collaboration_boost` 字段；`test_model_matrix.py` 新增 `TestCollaborationBoost` 测试类（4 用例） |
| 2026-03-19 | Phase 6.5 深度思考双验证: verification_service.py 新增 `_verify_by_deep_think()`（并行调用 DeepSeek R1 + Kimi K2 Thinking）+ `should_verify()` 新增 config 参数和 consult_expert 触发条件 + `verify_response()` 新增 deep_think_review 分支 + `_verify_by_model()` 新增 max_reply_len 参数；chat_service.py 传入 config；config.yaml/config.example.cn.yaml/config.example.us.yaml 新增 verification.deep_think 配置段；test_verification_service.py 新增 7 个用例（34 总计） |
