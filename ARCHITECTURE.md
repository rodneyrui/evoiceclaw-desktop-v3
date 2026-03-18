# eVoiceClaw Desktop v3 — AI OS 架构方案

> 版本: v1.3 (新增 Phase 6/7 + 评测子系统 + 回复验证子系统)
> 日期: 2026-03-11
> 定位: AI Operating System — LLM 是 CPU，Skill 是程序，Function Calling 是指令集
> 状态: 待审批
> v1.1 变更: 新增 Skill 版本更新机制、审计 trace_id、UUID 占位符隐私恢复、发展路线图
> v1.2 变更: 新增 4.7 模型评测子系统详细设计、Phase 6（逻辑层合规）+ Phase 7（评测子系统）开发阶段、决策记录 #9-#13
> v1.3 变更: 新增 4.8 回复验证子系统（从 V2 迁移，三层验证：legacy/strong_model_review/auto_search_verify），对话引擎流程图插入验证环节

---

## 一、AI OS 核心理念

### 1.1 传统 OS 与 AI OS 映射

| 传统 OS 概念 | AI OS 对应 | 实现方式 |
|-------------|-----------|---------|
| **CPU** | LLM（执行引擎） | 多模型路由 + 降级 |
| **指令集** | Function Calling（27+ 硬工具） | OpenAI tool_use 协议 |
| **应用程序** | Skill（自然语言"程序"） | SKILL.md 文件 |
| **包管理器 + 应用审核** | 守门员 LLM（Gatekeeper） | 安装时改写 SKILL.md |
| **Shell** | 受控命令执行器 | 沙箱 + 白名单 + 审批 |
| **进程调度器** | LLMRouter（智能路由） | 意图分类 → 模型选择 → 降级 |
| **内存管理** | 隐私管道（Privacy Pipeline） | 串联 5 级数据流 |
| **文件系统权限** | 工作区沙箱 + 路径校验 | 白名单目录 |
| **防火墙** | 网络守卫（NetworkGuard） | 禁内网 + 域名限制 |
| **用户态/内核态隔离** | 认知隔离（Cognitive Isolation） | 敏感/非敏感数据分离 |
| **系统日志** | 审计管道（Audit Pipeline） | 全链路可追溯 |

### 1.2 设计原则

1. **安全第一，功能第二** — 所有数据流经隐私管道，所有 Skill 经守门员审查
2. **管道化架构** — 核心子系统是串联管道，不是分散模块
3. **最小权限** — Skill 只能使用声明的工具，Shell 命令需审批
4. **可审计** — 每个操作有完整的审计日志
5. **向量原生** — LanceDB 作为核心存储引擎，贯穿实体映射、记忆、蒸馏

---

## 二、系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (React 19 + Vite)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │  对话界面  │ │ Skill市场 │ │ 工作区    │ │ 系统管理(设置等)  │   │
│  └─────┬────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘   │
│        └───────────┴────────────┴────────────────┘              │
│                           │ SSE / REST                          │
└───────────────────────────┼─────────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────────┐
│                     API 网关层 (FastAPI)                         │
│                 /chat  /skills  /config  /memory  ...           │
└───────────────────────────┼─────────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────────┐
│                                                                  │
│  ┌─────────────────── 隐私管道 (Privacy Pipeline) ──────────────┐│
│  │                                                               ││
│  │  用户输入                                                     ││
│  │    ↓                                                          ││
│  │  ① 认知隔离器 (Cognitive Isolator)                           ││
│  │    │ 分离敏感/非敏感数据流                                    ││
│  │    ↓                                                          ││
│  │  ② 实体类别映射器 (Entity Mapper)  ←→ [LanceDB: entities]   ││
│  │    │ 向量语义识别实体类型                                     ││
│  │    ↓                                                          ││
│  │  ③ 动态上下文压缩器 (Context Compressor)                     ││
│  │    │ 压缩后的安全上下文                                       ││
│  │    ↓                                                          ││
│  │  ④ 记忆注入器 (Memory Injector)    ←→ [LanceDB: memories]   ││
│  │    │ 三层渐进式记忆注入                                       ││
│  │    ↓                                                          ││
│  │  ⑤ 记忆蒸馏器 (Memory Distiller)  ←→ [LanceDB: distilled]  ││
│  │    │ 规则 + 向量长期沉淀                                      ││
│  │    ↓                                                          ││
│  │  安全上下文 → 送入 LLM 内核                                  ││
│  │                                                               ││
│  └───────────────────────────────────────────────────────────────┘│
│                            │                                      │
│  ┌────────────── LLM 内核 (Kernel) ──────────────────────────┐   │
│  │                                                            │   │
│  │  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐  │   │
│  │  │ SmartRouter  │───→│  LLMRouter   │───→│ API/CLI      │  │   │
│  │  │ (意图分类)   │    │ (模型路由)    │    │ Provider     │  │   │
│  │  └─────────────┘    └──────────────┘    └──────────────┘  │   │
│  │         │                                      │           │   │
│  │         │           ┌──────────────┐           │           │   │
│  │         └──────────→│ ModelMatrix  │───────────┘           │   │
│  │                     │ (能力评分)    │                       │   │
│  │                     └──────────────┘                       │   │
│  │                                                            │   │
│  │  ┌─────────────────────────────────────────────────────┐  │   │
│  │  │              硬工具集 (Hard Tools)                    │  │   │
│  │  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │  │   │
│  │  │  │ 记忆    │ │ 文件    │ │ 网络    │ │ 工作区  │       │  │   │
│  │  │  │ recall  │ │ read   │ │ http   │ │ get    │       │  │   │
│  │  │  │ save    │ │ write  │ │ fetch  │ │ list   │       │  │   │
│  │  │  │ delete  │ │ list   │ │ search │ │ register│      │  │   │
│  │  │  └────────┘ └────────┘ └────────┘ └────────┘       │  │   │
│  │  │  ┌────────┐ ┌────────┐ ┌────────────────┐          │  │   │
│  │  │  │ Skill  │ │ 数据库  │ │ Shell (受控)    │          │  │   │
│  │  │  │ search │ │ query  │ │ exec_command   │          │  │   │
│  │  │  │ install│ │        │ │ (沙箱+审批)     │          │  │   │
│  │  │  │ use    │ │        │ │                │          │  │   │
│  │  │  └────────┘ └────────┘ └────────────────┘          │  │   │
│  │  └─────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                            │                                      │
│  ┌────────────── 安全层 (Security Layer) ─────────────────────┐  │
│  │                                                             │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐ │  │
│  │  │ Gatekeeper  │  │ NetworkGuard │  │ Shell Sandbox     │ │  │
│  │  │ (安装时审查) │  │ (网络防火墙)  │  │ (命令沙箱+审批)  │ │  │
│  │  └─────────────┘  └──────────────┘  └───────────────────┘ │  │
│  │  ┌─────────────┐  ┌──────────────┐                        │  │
│  │  │ AuditLog    │  │ IntentGuard  │                        │  │
│  │  │ (审计日志)   │  │ (意图安全)    │                        │  │
│  │  └─────────────┘  └──────────────┘                        │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌────────────── 存储层 (Storage Layer) ──────────────────────┐   │
│  │                                                             │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐  │   │
│  │  │ LanceDB  │    │ SQLite   │    │ 文件系统              │  │   │
│  │  │ (向量)    │    │ (结构化)  │    │ config.yaml          │  │   │
│  │  │          │    │          │    │ secrets.yaml          │  │   │
│  │  │ entities │    │ sessions │    │ skills/               │  │   │
│  │  │ memories │    │ audit    │    │ workspaces/           │  │   │
│  │  │ distilled│    │ tasks    │    │ journals/             │  │   │
│  │  │ skills   │    │ users    │    │                       │  │   │
│  │  └──────────┘    └──────────┘    └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│                     后端 (Python / FastAPI)                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## 三、目录结构

```
desktop-v3/
├── ARCHITECTURE.md                    # 本文件
├── README.md                          # 项目说明
│
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口 + 生命周期管理
│   │   │
│   │   ├── api/v1/                    # REST API 路由层
│   │   │   ├── chat.py                # POST /chat (SSE 流式)
│   │   │   ├── config.py              # GET/PUT /config, PUT /secrets
│   │   │   ├── skills.py              # Skill 搜索/安装/卸载
│   │   │   ├── memory.py              # 记忆 CRUD + 语义召回
│   │   │   ├── workspace.py           # 工作区管理
│   │   │   ├── auth.py                # 认证
│   │   │   └── system.py              # 健康检查/统计/审计日志
│   │   │
│   │   ├── kernel/                    # ═══ LLM 内核 ═══
│   │   │   ├── __init__.py
│   │   │   ├── router/               # 智能路由子系统
│   │   │   │   ├── smart_router.py    # 三层路由：快速路径 → kNN 向量预测(~30ms) → LLM 降级(~500ms) → 模型选择
│   │   │   │   ├── knn_predictor.py   # kNN 需求向量预测器：bge-small 编码 + 2026 条锚点 + top-5 加权回归
│   │   │   │   ├── llm_router.py      # 模型路由：API/CLI 通道分派 + 降级
│   │   │   │   └── model_matrix.py    # 15 维能力评分矩阵（12 能力 + 3 规格，20+ 模型）
│   │   │   │
│   │   │   ├── providers/             # LLM 提供商适配
│   │   │   │   ├── api_provider.py    # API 通道（LiteLLM 统一接口）
│   │   │   │   ├── cli_provider.py    # CLI 通道（Claude/本地模型）
│   │   │   │   └── health.py          # Provider 健康度追踪（指数退避）
│   │   │   │
│   │   │   └── tools/                 # 硬工具集（系统调用）
│   │   │       ├── registry.py        # ToolRegistry 中心注册表
│   │   │       ├── executor.py        # ToolExecutor 执行引擎
│   │   │       ├── protocol.py        # SkillProtocol 抽象基类
│   │   │       │
│   │   │       └── builtin/           # 内置硬工具
│   │   │           ├── memory_ops.py   # recall_memory, save_memory, delete_memory
│   │   │           ├── filesystem.py   # read_file, write_file, list_directory
│   │   │           ├── network.py      # http_request, web_fetch, web_search
│   │   │           ├── workspace.py    # get/list/register/activate_workspace
│   │   │           ├── skill_mgmt.py   # search/install/uninstall/list_skills
│   │   │           ├── shell.py        # exec_command（受控 Shell）
│   │   │           ├── database.py     # query_database
│   │   │           └── browser.py      # browser_tool
│   │   │
│   │   ├── pipeline/                  # ═══ 隐私管道 ═══
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py            # 管道编排器（串联 5 级）
│   │   │   ├── cognitive_isolator.py  # ① 认知隔离器
│   │   │   ├── entity_mapper.py       # ② 实体类别映射器（LanceDB）
│   │   │   ├── context_compressor.py  # ③ 动态上下文压缩器
│   │   │   ├── memory_injector.py     # ④ 三层渐进式记忆注入器
│   │   │   └── memory_distiller.py    # ⑤ 记忆蒸馏器（规则+向量）
│   │   │
│   │   ├── memory/                    # ═══ 分层语义记忆系统 ═══
│   │   │   ├── __init__.py
│   │   │   ├── store.py               # 记忆存储引擎（LanceDB + SQLite）
│   │   │   ├── semantic_search.py     # 向量语义检索
│   │   │   ├── auto_extractor.py      # LLM 自动抽取记忆
│   │   │   ├── journal.py             # 对话日志持久化
│   │   │   └── models.py              # Memory 数据模型
│   │   │
│   │   ├── security/                  # ═══ 安全层 ═══
│   │   │   ├── __init__.py
│   │   │   ├── gatekeeper/            # 守门员子系统
│   │   │   │   ├── gatekeeper.py      # Gatekeeper 主逻辑（调用审查 LLM）
│   │   │   │   ├── prompt.py          # V5 System Prompt 存储
│   │   │   │   └── models.py          # 审查结果数据模型
│   │   │   │
│   │   │   ├── shell_sandbox.py       # Shell 沙箱（白名单+审批+超时）
│   │   │   ├── network_guard.py       # 网络防火墙（禁内网+域名限制）
│   │   │   ├── intent_analyzer.py     # 意图安全分析
│   │   │   └── audit.py               # 审计日志（全链路 trace_id 追踪）
│   │   │
│   │   ├── services/                  # ═══ 业务服务层 ═══
│   │   │   ├── chat_service.py        # 对话引擎（流式 + 工具循环）
│   │   │   ├── skill_service.py       # Skill 生命周期管理
│   │   │   ├── workspace_service.py   # 工作区管理
│   │   │   ├── soul_service.py        # 人格系统
│   │   │   ├── quota_service.py       # 额度管理
│   │   │   └── verification_service.py  # 回复验证（三层验证 + 单 Provider 自动禁用）
│   │   │
│   │   ├── infrastructure/            # ═══ 基础设施 ═══
│   │   │   ├── db.py                  # SQLite 连接管理
│   │   │   ├── vector_db.py           # LanceDB 连接管理
│   │   │   ├── sse.py                 # SSE 流式推送
│   │   │   ├── sandbox.py             # 脚本执行沙箱
│   │   │   └── usage_repo.py          # API 使用量统计
│   │   │
│   │   ├── core/                      # ═══ 核心配置 ═══
│   │   │   ├── config.py              # YAML 配置 + Secrets 分离
│   │   │   └── security.py            # JWT 认证
│   │   │
│   │   └── domain/                    # ═══ 领域模型 ═══
│   │       ├── models.py              # ChatMessage, StreamChunk, ToolCall
│   │       └── events.py              # 系统事件定义
│   │
│   ├── config.yaml                    # 非敏感配置
│   ├── secrets.yaml                   # API Key（.gitignore）
│   ├── requirements.txt
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── app/
│   │   │   ├── routes.tsx             # 路由定义
│   │   │   └── providers.tsx          # React Query 等全局 Provider
│   │   │
│   │   ├── features/                  # 按功能域拆分
│   │   │   ├── chat/                  # 核心对话
│   │   │   │   ├── ChatPage.tsx
│   │   │   │   ├── useDirectChat.ts
│   │   │   │   ├── directChatApi.ts   # SSE 流式
│   │   │   │   ├── MessageList.tsx
│   │   │   │   └── InputBar.tsx
│   │   │   │
│   │   │   ├── skills/                # Skill 市场
│   │   │   │   ├── SkillsPage.tsx
│   │   │   │   └── api.ts
│   │   │   │
│   │   │   ├── memory/               # 记忆管理
│   │   │   │   ├── MemoryPage.tsx
│   │   │   │   └── api.ts
│   │   │   │
│   │   │   ├── workspace/            # 工作区
│   │   │   │   ├── WorkspacePage.tsx
│   │   │   │   └── api.ts
│   │   │   │
│   │   │   ├── settings/             # 系统设置
│   │   │   │   ├── SettingsPage.tsx
│   │   │   │   ├── PrivacySettings.tsx  # 隐私级别/管道控制面板
│   │   │   │   └── api.ts
│   │   │   │
│   │   │   └── audit/                # 审计日志
│   │   │       ├── AuditPage.tsx
│   │   │       └── api.ts
│   │   │
│   │   ├── components/
│   │   │   ├── chat/                  # 聊天组件
│   │   │   └── ui/                    # Radix UI 包装
│   │   │
│   │   ├── shared/
│   │   │   ├── api/client.ts          # HTTP 客户端
│   │   │   ├── components/            # Layout, ErrorBoundary 等
│   │   │   └── hooks/                 # useTheme 等
│   │   │
│   │   └── i18n/                      # 国际化
│   │
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── data/                              # 运行时数据（.gitignore）
│   ├── vectors/                       # LanceDB 数据目录
│   │   ├── entities/                  # 实体类别映射向量
│   │   ├── memories/                  # 记忆向量
│   │   └── distilled/                 # 蒸馏记忆向量
│   ├── db/                            # SQLite 数据库
│   │   ├── main.db                    # 会话、任务、用户
│   │   └── audit.db                   # 审计日志（独立库）
│   ├── skills/                        # 已安装 Skill 目录
│   ├── workspaces/                    # 工作区数据
│   └── journals/                      # 对话日志
│
└── docs/
    ├── BACKLOG.md                     # 开发进度追踪
    ├── PRIVACY_PIPELINE.md            # 隐私管道详细设计
    ├── SHELL_SANDBOX.md               # Shell 沙箱详细设计
    ├── GATEKEEPER.md                  # 守门员集成文档
    └── MIGRATION_FROM_V2.md           # v2 组件迁移指南
```

---

## 四、核心子系统详细设计

### 4.1 隐私管道 (Privacy Pipeline) — AI OS 的内存管理

**设计原则**: 这是一条**串联管道**，所有进出 LLM 的数据必须经过它。不是分散的模块，而是一个统一的数据流处理器。

```
用户原始输入
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ ① 认知隔离器 (Cognitive Isolator)                       │
│                                                          │
│ 输入: 用户原始消息                                       │
│ 输出: { sensitive_stream, clean_stream, redaction_map }   │
│                                                          │
│ 工作原理:                                                │
│ - 正则快速扫描（身份证、银行卡、手机号等硬模式）          │
│ - 语义分类（调用小模型/规则引擎判断语义级敏感内容）       │
│ - 分离为两条数据流:                                      │
│   · sensitive_stream → 本地加密存储，不出设备             │
│   · clean_stream → 继续进入管道下一级                    │
│   · redaction_map → UUID 占位符映射表（供回复恢复使用）   │
│                                                          │
│ 占位符机制（UUID Redaction）:                            │
│ - 每个敏感数据项生成唯一 UUID 占位符                     │
│   例: "张三" → "__REDACTED_a1b2c3d4__"                   │
│   例: "13812345678" → "__REDACTED_e5f6g7h8__"            │
│ - 映射关系存入 redaction_map（会话级，内存持有）:         │
│   { "__REDACTED_a1b2c3d4__": {                           │
│       "original": "张三",                                │
│       "type": "PERSON_NAME",                             │
│       "sensitivity": "high"                              │
│   } }                                                    │
│ - redaction_map 会话结束后安全销毁                       │
│ - 不持久化到磁盘（除非用户明确开启隐私日志）             │
│                                                          │
│ 敏感度等级:                                              │
│ 🔴 极高(身份证/银行卡/密码) → UUID占位符，完全隔离       │
│ 🟠 高(姓名/电话/邮箱/金额) → UUID占位符，脱敏后通过     │
│ 🟡 中(日期/地点/一般描述) → 标记后通过                   │
│ 🟢 低(公开信息) → 直接通过                               │
│                                                          │
│ [未来扩展接口: 上下文保留脱敏]                           │
│ 初期: "张三" → "__REDACTED_xxx__"                        │
│ 未来: "张三" → "张先生"（保留语义上下文）                │
│ 预留: CognitiveIsolator.set_anonymization_strategy()     │
└─────────────────────┬───────────────────────────────────┘
                      │ clean_stream
                      ▼
┌─────────────────────────────────────────────────────────┐
│ ② 实体类别映射器 (Entity Mapper)                        │
│                                                          │
│ 输入: clean_stream                                       │
│ 输出: { entities: [{text, type, category, vector}], ... }│
│                                                          │
│ 存储: LanceDB entities 表                                │
│ - 向量语义匹配实体类型（人名→PERSON, 公司→ORG 等）       │
│ - 维护实体知识库（用户累积的实体图谱）                   │
│ - 为后续记忆注入提供实体上下文                           │
│                                                          │
│ 向量检索:                                                │
│ - 输入文本 → embedding → LanceDB.search(top_k=10)       │
│ - 结合元数据过滤（type, category, last_seen）            │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│ ③ 动态上下文压缩器 (Context Compressor)                  │
│                                                          │
│ 输入: 带实体标注的 clean_stream + 历史对话上下文          │
│ 输出: 压缩后的上下文（控制在 token 预算内）              │
│                                                          │
│ 策略:                                                    │
│ - 按重要性评分排序历史消息                               │
│ - 保留最近 N 轮完整对话                                  │
│ - 更早的对话压缩为摘要                                   │
│ - 实体相关历史优先保留                                   │
│ - 动态调整压缩比（根据模型 context window）              │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│ ④ 记忆注入器 (Memory Injector)                          │
│                                                          │
│ 输入: 压缩后的上下文 + 用户查询                          │
│ 输出: 增强上下文（注入了相关记忆）                       │
│                                                          │
│ 三层渐进式注入:                                          │
│                                                          │
│ Layer 1 — 核心事实 (Always Inject)                       │
│   用户基础信息、强偏好、重要事实                         │
│   来源: LanceDB memories 表 (type=fact, priority=high)   │
│                                                          │
│ Layer 2 — 相关记忆 (Query-Driven)                        │
│   与当前查询语义相关的记忆                               │
│   来源: LanceDB 向量相似度检索 (top_k=5)                 │
│   [未来扩展: 检索后 rerank 重排序]                       │
│   预留: MemoryInjector.set_reranker(reranker_fn)         │
│                                                          │
│ Layer 3 — 蒸馏规则 (Context-Driven)                      │
│   从历史交互中蒸馏出的行为规则                           │
│   来源: LanceDB distilled 表 (type=rule)                 │
│                                                          │
│ 注入方式: 拼接到 system_prompt 的记忆段                  │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│ 安全上下文 → 送入 LLM 内核执行                          │
│                                                          │
│ 返回路径（LLM 输出后）:                                  │
│                                                          │
│ LLM 回复                                                 │
│   ↓                                                      │
│ 隐私恢复器 (Privacy Restorer)                            │
│   ├─ 从 redaction_map 查找所有 UUID 占位符               │
│   ├─ "__REDACTED_a1b2c3d4__" → "张三"                    │
│   ├─ 检查上下文一致性（代词指代等）                      │
│   └─ [未来: LLM 辅助还原复杂引用]                        │
│   ↓                                                      │
│ 用户看到完整回复                                         │
└─────────────────────────────────────────────────────────┘
                      │
              (会话结束/过期时)
                      ▼
┌─────────────────────────────────────────────────────────┐
│ ⑤ 记忆蒸馏器 (Memory Distiller)                         │
│                                                          │
│ 输入: 完整会话历史                                       │
│ 输出: 蒸馏后的长期记忆                                   │
│                                                          │
│ 蒸馏类型:                                                │
│ - 事实记忆: 用户提到的具体事实 → LanceDB memories        │
│ - 偏好记忆: 用户表达的偏好 → LanceDB memories            │
│ - 行为规则: 交互模式中发现的规则 → LanceDB distilled     │
│ - 实体更新: 新发现的实体 → LanceDB entities              │
│                                                          │
│ 蒸馏方法:                                                │
│ - LLM 抽取（结构化 JSON 输出）                           │
│ - 向量化后 merge_insert（LanceDB upsert）                │
│ - 冲突解决：新记忆覆盖旧记忆（按 entity_id + type）      │
│ - 过期清理：TTL 策略 + 重要性评分衰减                    │
└─────────────────────────────────────────────────────────┘
```

### 4.2 LLM 内核 (Kernel)

**从 v2 迁移的核心组件**:

| 组件 | v2 文件 | v3 位置 | 迁移方式 |
|------|--------|---------|---------|
| SmartRouter | `smart_router.py` | `kernel/router/smart_router.py` | 15 维需求向量路由：快速路径 → kNN 向量预测(~30ms) → LLM 降级(~500ms) → 模型选择 |
| KNNPredictor | — | `kernel/router/knn_predictor.py` | 新建：bge-small 编码 + 2026 条 R1 标注锚点 + top-5 cosine kNN 加权回归 + .npy 缓存 + 置信度分流 |
| LLMRouter | `llm/llm_router.py` | `kernel/router/llm_router.py` | 直接迁移 |
| ModelMatrix | `model_matrix.py` | `kernel/router/model_matrix.py` | 直接迁移 |
| APIProvider | `llm/api_provider.py` | `kernel/providers/api_provider.py` | 直接迁移 |
| CLIProvider | `llm/cli_agent_provider.py` | `kernel/providers/cli_provider.py` | 直接迁移 |
| HealthTracker | `provider_health.py` | `kernel/providers/health.py` | 直接迁移 |
| ToolRegistry | `skill/tool_registry.py` | `kernel/tools/registry.py` | 直接迁移 |
| ToolExecutor | `skill/tool_executor.py` | `kernel/tools/executor.py` | 直接迁移 |
| SkillProtocol | `skill/protocol.py` | `kernel/tools/protocol.py` | 直接迁移 |
| 内置工具集 | `skill/builtin/*.py` | `kernel/tools/builtin/*.py` | 迁移 + 新增 shell.py |

**新增组件**:
- `kernel/tools/builtin/shell.py` — 受控 Shell 执行器（详见 4.3）

### 4.3 Shell 沙箱 (Shell Sandbox)

**核心问题**: 没有 Shell，himalaya、summarize 等 CLI Skill 无法执行。有了 Shell，安全风险大幅上升。

**三层防护设计**:

```
Skill 请求执行命令
    │
    ▼
┌──────────────────────────────────────────┐
│ Layer 1: 静态白名单（零延迟）            │
│                                           │
│ 允许的命令前缀:                           │
│ - himalaya *                              │
│ - summarize *                             │
│ - curl (GET only, 无 -d/-X POST)          │
│ - python3 -c (单行脚本，无文件操作)       │
│ - jq *                                    │
│ - date / cal / echo                       │
│                                           │
│ 绝对禁止:                                 │
│ - rm / rmdir / mv (删除/移动)             │
│ - chmod / chown / sudo / su               │
│ - ssh / scp / rsync                       │
│ - eval / exec / source                    │
│ - 管道到 curl/wget (数据渗出)             │
│ - > /dev/* 或 > /etc/* (系统文件写入)     │
│                                           │
│ 结果: ALLOW → Layer 2 | DENY → 拒绝      │
└──────────────┬───────────────────────────┘
               │ ALLOW
               ▼
┌──────────────────────────────────────────┐
│ Layer 2: 守门员动态审查（安装时已完成）   │
│                                           │
│ Skill 安装时，守门员 V5 已经:             │
│ - 审查了 SKILL.md 中的命令模式            │
│ - 改写为安全版本                          │
│ - 注入了防冲突指令                        │
│                                           │
│ 运行时仅验证:                             │
│ - 当前命令是否匹配 Skill 声明的命令模式   │
│ - 是否超出改写后 SKILL.md 的授权范围      │
│                                           │
│ 结果: MATCH → Layer 3 | MISMATCH → 拒绝  │
└──────────────┬───────────────────────────┘
               │ MATCH
               ▼
┌──────────────────────────────────────────┐
│ Layer 3: 运行时沙箱                       │
│                                           │
│ 执行约束:                                 │
│ - 超时: 30 秒（可配置）                   │
│ - 工作目录: 限制在工作区内                │
│ - 环境变量: 最小化（不继承用户完整 ENV）  │
│ - 输出限制: stdout/stderr 各 100KB        │
│ - 子进程: 禁止 fork bomb（ulimit）        │
│ - 网络: 仅允许白名单域名（继承 NetworkGuard）│
│                                           │
│ 可选: 高风险命令需用户实时审批            │
│ (通过 SSE 推送审批请求到前端)             │
└──────────────────────────────────────────┘
```

### 4.4 守门员集成 (Gatekeeper Integration)

**V5 已验证，集成方式**:

```
用户请求安装 Skill
    │
    ▼
┌─────────────────────────────────┐
│ 1. 下载 SKILL.md 原文          │
│    （从 ClawHub 或本地文件）     │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 2. 调用守门员 LLM               │
│    模型: Kimi K2.5（推荐）      │
│    或 DeepSeek V3（备选）       │
│    System Prompt: V5            │
│    Input: 原始 SKILL.md         │
│    Output: 改写后的 SKILL.md    │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 3. 保存改写结果 + 版本信息      │
│    原文 → skills/{name}/SKILL.md.original     │
│    改写 → skills/{name}/SKILL.md              │
│    审查报告 → skills/{name}/REVIEW.json       │
│    版本记录 → skills/{name}/VERSION.json      │
│                                                │
│    VERSION.json:                               │
│    {                                           │
│      "version": "1.0.0",                      │
│      "content_hash": "sha256:abc123...",       │
│      "reviewed_at": "2026-03-09T...",          │
│      "gatekeeper_model": "kimi-k2.5",         │
│      "gatekeeper_prompt_version": "v5"         │
│    }                                           │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 4. 提取 Shell 命令白名单        │
│    从改写后 SKILL.md 中提取     │
│    允许的命令模式 → ACTIONS.yaml │
│    供 Shell Sandbox Layer 2 使用 │
└─────────────────────────────────┘
```

**Skill 更新流程（v1.1 新增）**:

```
用户请求更新 Skill / 系统检测到新版本
    │
    ▼
┌──────────────────────────────────────────┐
│ 1. 下载新版 SKILL.md                     │
│    计算 content_hash (SHA-256)           │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ 2. 对比 VERSION.json 中的 content_hash   │
│    ├─ 相同 → 跳过审查（内容未变）        │
│    └─ 不同 → 进入增量审查               │
└──────────────┬───────────────────────────┘
               │ 不同
               ▼
┌──────────────────────────────────────────┐
│ 3. 增量审查                              │
│    守门员输入:                            │
│    - 新版 SKILL.md 原文                  │
│    - （不提供旧版，避免锚定效应）         │
│    守门员输出:                            │
│    - 重新改写后的 SKILL.md               │
│                                           │
│    注意: 视为全新安装进行完整审查，       │
│    不做 diff 增量审查（防止绕过）         │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ 4. 更新版本记录                          │
│    VERSION.json 更新 content_hash        │
│    保留旧版: SKILL.md.previous           │
│    更新 ACTIONS.yaml（Shell 白名单）     │
│    通知用户: "Skill XXX 已更新并重新审查" │
└──────────────────────────────────────────┘
```

### 4.5 分层语义记忆系统 (Layered Semantic Memory)

**存储引擎: LanceDB**

```
LanceDB 数据目录: data/vectors/

┌─────────────────────────────────────────────────────┐
│ Table: entities                                      │
│ 用途: 实体类别映射                                   │
│                                                       │
│ Schema:                                               │
│ - id: string (UUID)                                   │
│ - text: string (实体原文)                             │
│ - type: string (PERSON/ORG/LOCATION/PRODUCT/...)      │
│ - category: string (细分类别)                         │
│ - vector: float32[dim] (embedding)                    │
│ - metadata: json (来源、首次出现时间等)               │
│ - last_seen: timestamp                                │
│ - frequency: int (出现次数)                           │
│                                                       │
│ 索引: IVF-PQ (磁盘优先，低内存)                      │
│ 更新: merge_insert (按 text+type 做 upsert)          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ Table: memories                                      │
│ 用途: 用户记忆存储                                   │
│                                                       │
│ Schema:                                               │
│ - id: string (UUID)                                   │
│ - content: string (记忆内容)                          │
│ - type: string (fact/preference/summary/episode)      │
│ - priority: string (high/medium/low)                  │
│ - vector: float32[dim] (embedding)                    │
│ - source_conv_id: string (来源会话)                   │
│ - entities: list[string] (关联实体 ID)                │
│ - created_at: timestamp                               │
│ - last_recalled: timestamp                            │
│ - recall_count: int                                   │
│ - ttl_days: int (可选，过期天数)                      │
│                                                       │
│ 检索: 向量相似度 + 元数据过滤(type, priority)        │
│ 更新: merge_insert (按 content hash 做去重)          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ Table: distilled                                     │
│ 用途: 蒸馏规则存储                                   │
│                                                       │
│ Schema:                                               │
│ - id: string (UUID)                                   │
│ - rule: string (蒸馏出的行为规则，自然语言)           │
│ - type: string (behavior/preference/constraint)       │
│ - vector: float32[dim] (embedding)                    │
│ - confidence: float (0-1, 置信度)                     │
│ - evidence_count: int (支持该规则的交互次数)          │
│ - created_at: timestamp                               │
│ - updated_at: timestamp                               │
│                                                       │
│ 蒸馏: 会话结束时 LLM 抽取 → 向量化 → merge_insert   │
│ 强化: evidence_count 越高，注入优先级越高            │
│ 衰减: 长期未被强化的规则降低 confidence               │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ Table: skill_index (可选)                            │
│ 用途: Skill 语义索引（Skill 发现与推荐）             │
│                                                       │
│ Schema:                                               │
│ - skill_name: string                                  │
│ - description: string                                 │
│ - vector: float32[dim] (description embedding)        │
│ - capabilities: list[string]                          │
│ - installed: bool                                     │
└─────────────────────────────────────────────────────┘
```

**Embedding 模型选择**:
- 首选: `text-embedding-3-small` (OpenAI, 1536 维, 成本低)
- 备选: `BAAI/bge-small-zh-v1.5` (本地运行, 512 维, 中文优化)
- 可配置: 通过 config.yaml 切换

### 4.6 对话引擎 (Chat Service)

**从 v2 迁移 + 集成隐私管道**:

```
用户消息到达
    │
    ▼
生成 trace_id (UUID) — 贯穿本次请求全链路
    │
    ▼
URL 自动抓取（如有）
    │
    ▼
┌─ 隐私管道 ────────────────────────────┐
│ ① 认知隔离 → ② 实体映射 → ③ 上下文压缩 │
│ → ④ 记忆注入                           │
│ (每级操作记录 trace_id + 耗时)          │
└──────────────┬─────────────────────────┘
               │ 安全上下文
               ▼
SmartRouter.select_model()
    │
    ├─ 快速路径（问候/命令）→ 默认模型（0 延迟）
    ├─ kNN 向量预测（~30ms，bge-small + 2026 锚点 top-5 加权回归）
    │   ├─ 高/中置信度（std ≤ 1.42）→ 直接使用 15 维需求向量
    │   └─ 低置信度（std > 1.42）→ 降级 LLM 分类器
    └─ LLM 分类器降级（~500ms，轻量模型输出 15 维 JSON）
    │
    ▼
构建 system_prompt:
    Soul + Skill声明 + 记忆段 + 工作区上下文 + 安全约束
    │
    ▼
LLMRouter.stream_with_fallback()  [记录 trace_id + model_id]
    │
    ├─ 正常文本 → yield StreamChunk(type="text")
    │
    ├─ Tool Call → ToolExecutor.execute()  [记录 trace_id + tool_name]
    │   ├─ 普通工具 → 直接执行
    │   └─ Shell 命令 → Shell Sandbox 三层验证
    │       ├─ ALLOW → 沙箱执行 → yield tool_result
    │       └─ DENY → yield error + 拒绝原因
    │              [审计记录: trace_id + 被拒命令 + 拒绝层级 + 原因]
    │
    └─ 工具循环（最多 5 轮）
    │
    ▼
LLM 最终回复
    │
    ▼
隐私恢复（UUID 占位符 → 原始数据，通过 redaction_map）
    │
    ▼
┌─ 回复验证 (Verification) ─────────────────────┐
│ should_verify() — 确定性规则判断是否需要验证    │
│   ├─ 不需要 → 跳过                             │
│   └─ 需要 → verify_response(method)             │
│       ├─ legacy → 固定审核模型事实核查           │
│       ├─ strong_model_review → 交叉模型审核      │
│       └─ auto_search_verify → web_search 验证    │
│                                                   │
│ 验证结果:                                         │
│   ├─ verified=true → 正常发送                    │
│   ├─ search 验证 → 追加验证提示（不触发修正）    │
│   └─ verified=false + issues → 自动修正循环      │
│       构建修正 prompt → 同模型重新生成 → 发送    │
│       [审计: trace_id + 验证方法 + 结果 + 耗时]  │
└───────────────────────────────────────────────────┘
    │
    ▼
yield StreamChunk(type="end")
    │
    ▼
审计落盘: trace_id + 用户消息摘要 + 模型 + 工具调用链 + 验证结果 + 耗时
    │
    ▼
(会话过期时)
    ▼
⑤ 记忆蒸馏 → LanceDB
```

### 4.8 回复验证子系统 (Verification Subsystem) — AI OS 的质检员

> **来源**: 从 V2 `services/verification/verification_service.py`（591 行）迁移并适配 V3 架构
> **设计原则**: 确定性规则触发（不靠 LLM 判断是否需要验证），验证过程用户无感知
> **前提条件**: 需要 ≥2 个已启用的 API Provider；仅配置 1 个 Provider 时自动禁用（无法交叉验证）

**系统定位**: 回复验证子系统是 AI OS 的"质检员"，在 LLM 回复发送给用户之前进行质量把关：
1. **确定性触发** — 基于工具调用类型、内容模式、模型能力画像，用确定性规则判断是否需要验证
2. **交叉验证** — 弱模型的回复由强模型审核（模型能力画像驱动审核模型选择）
3. **搜索验证** — 高风险事实声称（投资/医疗/法律）通过 web_search 交叉核实
4. **自动修正** — 验证失败时自动构建修正 prompt，让原模型重新生成

```
LLM 回复完成（工具循环结束 + 隐私恢复后）
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ should_verify(user_msg, reply, tools_used, model_id, intent) │
│                                                               │
│ 第一优先级: 规则引擎驱动触发                                  │
│   触发 1: 弱模型处理高权重任务                                │
│     模型某维度 ≤3 且该意图需求权重 ≥7                         │
│     → method="strong_model_review"                            │
│                                                               │
│   触发 2: 模型处理其 avoid_for 任务                           │
│     路由规则中标注 avoid_for 包含当前意图                     │
│     → method="strong_model_review"                            │
│                                                               │
│   触发 3: 高风险事实声称                                      │
│     正则检测投资建议/医疗方案/法律条款/统计数据               │
│     → method="auto_search_verify"                             │
│                                                               │
│ 第二优先级: 传统硬编码规则                                    │
│   使用了写操作工具(install_skill/save_memory等)               │
│   → method="legacy"                                           │
│   回复包含代码块(≥20字符)                                     │
│   → method="legacy"                                           │
│   回复包含操作性关键词(sudo/rm/pip install/请执行等)          │
│   → method="legacy"                                           │
│                                                               │
│ 跳过条件:                                                     │
│   回复 < 50 字符                                              │
│   使用了外部数据工具(web_search/http_request等，验证LLM无法   │
│   核实实时数据)                                               │
└──────────────┬───────────────────────────────────────────────┘
               │ (True, method)
               ▼
┌──────────────────────────────────────────────────────────────┐
│ verify_response(user_msg, reply, config, method, model_id)    │
│                                                               │
│ ┌─ auto_search_verify ───────────────────────────────────┐   │
│ │ 1. 提取关键事实声称（正则: 数字+实体+数据来源）        │   │
│ │ 2. web_search 逐条验证（max_results=3）                │   │
│ │ 3. 构建验证摘要 → 追加到回复末尾                       │   │
│ │ 4. verified=true（搜索验证只追加提示，不判定对错）     │   │
│ │ ⚠ web_search 不可用时降级为 strong_model_review        │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                               │
│ ┌─ strong_model_review ──────────────────────────────────┐   │
│ │ 1. select_auditor_model():                             │   │
│ │    找出触发维度的短板 → 从可用模型中选择:              │   │
│ │    ✓ 该维度评分 ≥4                                     │   │
│ │    ✓ 成本 ≤3（不用最贵的模型做审核）                   │   │
│ │    ✓ 排除原模型（不能自己审自己）                      │   │
│ │    兜底: qwen-plus                                     │   │
│ │ 2. 构建审核 prompt → 审核模型生成 JSON 结果            │   │
│ │ 3. 解析: verified / confidence / issues / summary      │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                               │
│ ┌─ legacy ───────────────────────────────────────────────┐   │
│ │ 固定使用 config.verification.model（默认 qwen-plus）   │   │
│ │ 通用事实核查 prompt → JSON 结果                        │   │
│ └────────────────────────────────────────────────────────┘   │
└──────────────┬───────────────────────────────────────────────┘
               │ VerificationResult
               ▼
┌──────────────────────────────────────────────────────────────┐
│ 结果处理                                                      │
│   ├─ verified=true → 正常发送给用户                          │
│   ├─ search 验证 → 追加验证提示，不触发修正                  │
│   └─ verified=false + issues 非空 → 自动修正                 │
│       1. 构建修正 prompt: 原始问题 + 发现的问题列表          │
│       2. 同一模型重新生成回复                                │
│       3. 新回复追加到消息历史                                │
│       4. yield 修正内容给客户端                              │
│       [审计: VERIFICATION_PASSED / VERIFICATION_FAILED /      │
│              VERIFICATION_CORRECTED + trace_id + 耗时]       │
└──────────────────────────────────────────────────────────────┘
```

**V2 → V3 适配要点**:

| 维度 | V2 实现 | V3 适配 |
|------|---------|---------|
| 模型能力数据 | `KNOWN_MODELS` 静态字典 | `evaluation/matrix/model_matrix.py` 动态矩阵（LanceDB） |
| 路由规则读取 | `rule_loader` 模块 | `data/generated_rules/routing_rules.yaml` YAML 读取 |
| LLM 调用 | `get_router().stream()` | V3 `LLMRouter.stream()` |
| web_search 访问 | `get_tool_registry().get("web_search")` | V3 `ToolRegistry` |
| 审计日志 | 无 | 集成 `security/audit.py`，记录 trace_id + 验证事件 |
| 使用量统计 | `usage_repo.log_usage()` | V3 `infrastructure/usage_repo.py` |
| 文件位置 | `services/verification/verification_service.py` | `services/verification_service.py` |

**关键组件**:

| 组件 | 文件 | 职责 |
|------|------|------|
| 验证触发器 | `services/verification_service.py` | `should_verify()` 确定性规则判断 |
| 验证执行器 | `services/verification_service.py` | `verify_response()` 三种验证方法 |
| 审核模型选择器 | `services/verification_service.py` | `select_auditor_model()` 基于模型能力画像 |
| 验证结果模型 | `services/verification_service.py` | `VerificationResult` 数据类 |
| ChatService 集成 | `services/chat_service.py` | LLM 回复后调用验证，失败时触发修正循环 |

### 4.9 模型评测子系统 (Evaluation Subsystem) — AI OS 的质检部

> **详细设计文档**: `docs/EVALUATION_SYSTEM.md`

**设计原则**: 完全后台化，用户无感知，系统自主优化。

**系统定位**: 模型评测子系统是 AI OS 的"质检部"与"人事部"：
1. **持续评测** — 在系统空闲时自动评测已接入的 LLM 模型
2. **能力矩阵** — 维护 12 维能力评分 + 3 维规格需求（成本敏感度/速度优先级/上下文需求），路由评分公式动态调整
3. **规则生成** — 基于评测数据，由规则生成器自动生成路由规则、Prompt 模板、人格映射、守门员策略
4. **动态优化** — SmartRouter / ChatService / Gatekeeper 热加载规则，无需重启

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      模型评测子系统架构                                   │
│                                                                          │
│  触发层                                                                  │
│  ┌───────────────┐  ┌────────────────┐  ┌──────────────────┐            │
│  │ 新模型检测     │  │ 定时全量(月)    │  │ 空闲检测(CPU<20%) │            │
│  └───────┬───────┘  └───────┬────────┘  └────────┬─────────┘            │
│          └──────────────────┼────────────────────┘                      │
│                             ▼                                            │
│  调度层                                                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ Scheduler — 任务队列 + 优先级 + 状态机    │                           │
│  │ PENDING → QUEUED → RUNNING → COMPLETED   │                           │
│  │                          ↘ FAILED (3次重试)│                          │
│  │                          ↘ CANCELLED       │                          │
│  └──────────────────────┬───────────────────┘                           │
│                         ▼                                                │
│  执行层                                                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ Executor — 遍历 11 维 × 15 题 = 165 次调用│                          │
│  │ 调用 LiteLLM APIProvider → 评分器打分     │                           │
│  │ 结果写入 LanceDB model_evaluations 表     │                           │
│  └──────────────────────┬───────────────────┘                           │
│                         ▼                                                │
│  规则层                                                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ RuleGenerator — 生成 5 个 YAML                    │                          │
│  │ ① routing_rules.yaml (SmartRouter 消费)   │                          │
│  │ ② model_prompts.yaml (ChatService 消费)   │                          │
│  │ ③ agent_personalities.yaml (未来 soul)     │                          │
│  │ ④ gatekeeper_overrides.yaml (守门员消费)   │                          │
│  └──────────────────────┬───────────────────┘                           │
│                         ▼                                                │
│  加载层                                                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ HotReload — 30s 轮询 YAML 文件变更        │                          │
│  │ 回调通知 SmartRouter / ChatService 重载    │                          │
│  └──────────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
```

**能力矩阵（15 维需求向量 + 3 维规格数据）**:

| 分类 | 维度 | 说明 |
|------|------|------|
| 可测量（12 维） | `coding`, `math_reasoning`, `logic`, `long_context`, `agent_tool_use`, `chinese_writing`, `knowledge_tech`, `knowledge_legal`, `knowledge_business`, `instruction_following`, `knowledge_medical`, `reasoning`(派生) | Benchmark 题集评测，0-100 分 |
| 规格需求（3 维） | `cost_sensitivity`, `speed_priority`, `context_need` | 由 SmartRouter 预测，0-10 权重，动态调整评分公式 |
| 规格数据（3 维） | `context_window`, `cost_input_per_m`, `cost_output_per_m` | 供应商数据，被规格需求维度消费 |

**数据存储**:
- **LanceDB `model_evaluations` 表**: 16 维评分 + 延迟 + 成本 + 元数据（当前 17 个预置模型）
- **SQLite `evaluation_queue` 表**: 任务状态机（PENDING/QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED）
- **SQLite `rule_generation_state` 表**: 规则生成状态追踪

**触发机制（完全自动）**:
| 触发场景 | 时机 | 实现 |
|---------|------|------|
| 首次启动 | `model_evaluations` 表为空 | `preset_loader.py` 加载 17 个预置模型数据 |
| 新模型添加 | 用户新增 API Key | `scheduler.py` 监听配置变更，创建评测任务 |
| 定时全量 | 每月 1 号凌晨 2 点 | `scheduler.py` 内置 cron |
| 空闲评测 | CPU < 20% 持续 5 分钟 | `idle_monitor.py` (psutil) |
| 规则生成 | 评测完成 60s 防抖 + 每周一凌晨 3 点 | `rule_generator.py` |
| 使用量触发 | 对话轮次阈值（50/100/200/500） | `usage_trigger.py` 计数器 |

**关键组件**:

| 组件 | 文件 | 职责 |
|------|------|------|
| 评测题集 | `evaluation/cases/*.py` | 11 维 × 15 题 = 165 题（内嵌自 eVoiceClawBenchmark） |
| 评分器 | `evaluation/scoring/*.py` | 6 种评分策略（exact/keyword/rubric/tool_call/code_test/format_check） |
| 调度器 | `evaluation/scheduler/scheduler.py` | 任务队列管理 + 优先级 + 状态转换 + 取消支持 |
| 执行器 | `evaluation/scheduler/executor.py` | 调用 LLM 跑题 + 评分 + 写 LanceDB（支持 asyncio.Event 取消） |
| 空闲监控 | `evaluation/scheduler/idle_monitor.py` | CPU/内存/用户活动检测 |
| 推理模型检测 | `evaluation/rules/reasoning_model_detector.py` | 自动检测当前可用的规则生成模型 |
| 规则生成器 | `evaluation/rules/rule_generator.py` | 构造 Prompt → 调用模型 → 解析 YAML → 校验 → 写文件 + 备份 |
| 热加载 | `evaluation/rules/hot_reload.py` | 30s 轮询 YAML 变更 → 回调通知消费方 |
| 使用量触发 | `evaluation/rules/usage_trigger.py` | 对话轮次阈值触发规则重生成 |
| 动态矩阵 | `evaluation/matrix/model_matrix.py` | 从 LanceDB 读取评分 + 内存缓存（TTL 1h）+ 路由规则 YAML 加载 |
| 预置加载器 | `evaluation/preset_loader.py` | 首次启动从 `preset_evaluations.json` 注入 LanceDB |

---

## 五、v2 → v3 迁移计划

### 5.1 直接迁移（代码基本不变）

| 模块 | v2 路径 | v3 路径 | 说明 |
|------|--------|---------|------|
| SmartRouter | `services/smart_router.py` | `kernel/router/smart_router.py` | 三层路由策略 |
| LLMRouter | `services/llm/llm_router.py` | `kernel/router/llm_router.py` | API/CLI 分派 |
| ModelMatrix | `infrastructure/model_matrix.py` | `kernel/router/model_matrix.py` | 15 维评分（12 能力 + 3 规格需求） |
| APIProvider | `services/llm/api_provider.py` | `kernel/providers/api_provider.py` | LiteLLM 适配 |
| CLIProvider | `services/llm/cli_agent_provider.py` | `kernel/providers/cli_provider.py` | CLI 代理 |
| HealthTracker | `infrastructure/provider_health.py` | `kernel/providers/health.py` | 指数退避 [迁移时加入 jitter] |
| ToolRegistry | `services/skill/tool_registry.py` | `kernel/tools/registry.py` | 工具注册 |
| ToolExecutor | `services/skill/tool_executor.py` | `kernel/tools/executor.py` | 工具执行 [迁移时加入 schema 校验] |
| SkillProtocol | `services/skill/protocol.py` | `kernel/tools/protocol.py` | 抽象基类 |
| 内置工具(大部分) | `services/skill/builtin/*.py` | `kernel/tools/builtin/*.py` | 26 个工具 |
| Config | `core/config.py` | `core/config.py` | YAML+Secrets |
| SSE | `infrastructure/sse.py` | `infrastructure/sse.py` | 流式推送 |
| DB | `infrastructure/db.py` | `infrastructure/db.py` | SQLite |

### 5.2 重构迁移（需要适配）

| 模块 | 变更内容 |
|------|---------|
| ChatService | 插入隐私管道调用，移除 CrewAI 依赖 |
| MemoryStore | 从纯 SQLite 迁移到 LanceDB + SQLite 混合 |
| SoulService | 简化，移除旧版规则集成（v3 可后续加回） |
| WorkspaceService | 简化，保持核心功能 |
| SecurityGuard | 拆分为 NetworkGuard + IntentAnalyzer + ShellSandbox |

### 5.3 全新开发

| 模块 | 优先级 | 说明 |
|------|--------|------|
| 隐私管道 5 级 | P0 | AI OS 核心，必须第一个完成 |
| Shell 沙箱 | P0 | Skill 执行能力的前提 |
| 守门员集成 | P1 | V5 已验证，需要集成代码 |
| LanceDB 基础设施 | P0 | 向量存储引擎 |
| 审计日志 | P1 | 安全可追溯 |

### 5.4 不迁移（v2 专属）

| 模块 | 原因 |
|------|------|
| CrewAI 适配器 | v3 不使用 CrewAI 框架 |
| Crew 注册表/执行器 | v3 用 Skill 替代 Crew |
| Orchestrator | v3 的编排由 SmartRouter + ToolExecutor 完成 |
| 旧版规则生成器(54K行) | 过于庞大，v3 初期不需要 |
| Benchmark 评测 | v3 稳定后再加 |
| 任务服务 | v3 简化为对话模式，不需要后台任务队列 |

---

## 六、技术栈

### 后端

| 类别 | 技术 | 版本 | 说明 |
|------|------|------|------|
| Web 框架 | FastAPI | 最新 | 异步 + SSE |
| LLM 适配 | LiteLLM | 最新 | 统一多模型接口 |
| 向量数据库 | LanceDB | 最新 | 嵌入式，Rust+Arrow |
| 关系数据库 | SQLite | 系统自带 | 会话/任务/审计 |
| Embedding | OpenAI text-embedding-3-small 或 本地 BGE | - | 可配置 |
| 配置 | PyYAML | - | config.yaml + secrets.yaml |
| Python | 3.12+ | - | async/await |

### 前端

| 类别 | 技术 | 说明 |
|------|------|------|
| 框架 | React 19 + TypeScript | 从 v2 沿用 |
| 构建 | Vite 7 | 从 v2 沿用 |
| 样式 | Tailwind CSS 4 | 从 v2 沿用 |
| 组件库 | Radix UI | 从 v2 沿用 |
| 状态 | TanStack React Query | 从 v2 沿用 |
| 国际化 | i18next | 从 v2 沿用 |

---

## 七、开发阶段

### Phase 0: 骨架搭建
- 创建目录结构
- 初始化后端 FastAPI 项目
- 初始化前端 React 项目
- 配置 LanceDB + SQLite
- config.yaml / secrets.yaml 机制

### Phase 1: LLM 内核
- 迁移 SmartRouter + LLMRouter + ModelMatrix
- 迁移 Provider 层（API + CLI + Health）
- 迁移 ToolRegistry + ToolExecutor + SkillProtocol
- 迁移内置硬工具集（不含 Shell）
- 基础对话流程跑通（无隐私管道、无 Shell）

### Phase 2: 隐私管道
- ① 认知隔离器
- ② 实体类别映射器（LanceDB entities 表）
- ③ 动态上下文压缩器
- ④ 记忆注入器（LanceDB memories 表）
- ⑤ 记忆蒸馏器（LanceDB distilled 表）
- 管道编排器（串联 5 级）
- 集成到 ChatService

### Phase 3: Shell + 守门员
- Shell 沙箱三层防护
- 守门员 V5 集成
- Skill 安装流程（下载→审查→改写→白名单提取）
- 审计日志

### Phase 4: 前端
- 迁移核心对话界面
- 隐私控制面板
- Skill 市场
- 工作区管理
- 审计日志查看

### Phase 5: 打磨与测试
- 端到端安全测试
- 性能优化
- 文档完善

### Phase 6: 逻辑层合规
- 对照 AI OS 宪法（29 条）补齐实现与设计规范的差距
- 审计日志增加 workspace_id、ToolExecutor 权限检查+审计
- SkillProtocol 权限声明、NetworkGuard 域名白名单
- 工作区记忆隔离（LanceDB 全链路 workspace_id 过滤）
- Shell 安全级别 L1/L2/L3、工作区隔离配置+敏感变量
- 自举标记工具、Skill 细粒度授权、config.yaml 安全配置
- 安全审计（11 项静态分析 → 修复 SA-2/SA-7/SA-8/SA-10/SA-11）

### Phase 6.5: 回复验证子系统
- 从 V2 迁移 `verification_service.py`（三层验证：legacy/strong_model_review/auto_search_verify）
- 确定性规则触发 + 交叉模型审核（模型能力画像驱动审核模型选择）
- 搜索验证（高风险事实声称通过 web_search 交叉核实）
- 自动修正循环（验证失败 → 同模型重新生成）
- 集成到 ChatService（隐私恢复后、发送前）
- 审计日志记录验证事件

### Phase 7: 模型评测子系统（完全后台化）
- 7A 数据层：内嵌 Benchmark 题集（155 题 11 维）+ LanceDB/SQLite 表 + 预置数据（17 模型）
- 7B 动态矩阵：ModelMatrix 从 LanceDB 动态读取 + 内存缓存 TTL 1h + SmartRouter 无感迁移
- 7C 调度+执行：空闲监控 + 任务队列状态机 + 评测执行器 + API 端点 + 取消机制
- 7D 规则生成：规则生成模型自动检测 + 5 个 YAML 规则文件 + Schema 校验 + 热加载 + 使用量触发

---

## 八、关键设计决策记录

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | 向量数据库 | LanceDB | 嵌入式、Rust 实现、磁盘优先低内存、完整 CRUD、Apache 2.0 |
| 2 | 隐私管道架构 | 串联管道（非分散模块） | 用户明确要求；数据流必须有确定性的处理顺序 |
| 3 | Shell 执行 | 三层防护沙箱 | 没有 Shell 产品力不足；三层防护平衡安全与功能 |
| 4 | 守门员模型 | Kimi K2.5（推荐）/ DeepSeek V3（备选） | K2.5 tool_use benchmark 满分；V3 已在 V5 测试中验证 |
| 5 | 项目方式 | 全新 desktop-v3 | 用户决策；核心组件从 v2 迁移，架构重新设计 |
| 6 | CrewAI | 不使用 | v3 用 Skill + Function Calling 替代多 Agent 编排 |
| 7 | Embedding 模型 | 可配置（API/本地） | 灵活性；API 首选 text-embedding-3-small，本地首选 BGE |
| 8 | 前端技术栈 | 沿用 v2 (React+Vite+Tailwind) | 成熟、稳定、无需重新学习 |
| 9 | 评测子系统 UI | 无 UI，完全后台 | 用户无感知，系统自主优化；降低前端复杂度 |
| 10 | Benchmark 代码 | 内嵌到 V3（非独立包） | 简化维护，V3 统一更新题集和评分器 |
| 11 | 预置数据范围 | 全部 17 个模型 | 开箱即用，逐步替换为真实评测数据 |
| 12 | 规则生成模型 | 按需自动检测，运行时确定 | 自动从当前 config 中检测可用模型，无需手动配置 |
| 13 | 规则生成触发 | 完全自动（防抖+定时+使用量） | 后台化原则；评测完成 60s 防抖 + 每周定时 + 对话轮次阈值 |

---

## 九、与 v2 的关键差异

| 维度 | v2 | v3 |
|------|----|----|
| 定位 | 多 Agent 协同工作台 | AI Operating System |
| 核心框架 | CrewAI（多 Agent 编排） | 单 LLM + Function Calling + Skill |
| 安全模型 | 基础（NetworkGuard + IntentAnalyzer） | 完整（守门员+隐私管道+Shell沙箱+审计） |
| 向量数据库 | ChromaDB（辅助组件） | LanceDB（核心基础设施） |
| 记忆系统 | SQLite 关键词搜索 | 分层语义记忆（LanceDB 向量检索） |
| 隐私保护 | 无 | 5 级串联隐私管道 |
| Shell | 无 | 三层防护沙箱 |
| Skill 审查 | 无 | 守门员 V5 安装时改写 |
| 数据流 | 分散处理 | 管道化（所有数据经隐私管道） |

---

## 十、发展路线图 (Roadmap)

> 以下功能不在初始开发阶段（Phase 0-5）范围内，但架构设计已预留接口。
> 按优先级排序，每项标注了预留的接口位置。

### R1: 记忆召回重排序 (Rerank)

**问题**: 向量相似度检索可能召回语义相似但实际无关的记忆，降低记忆注入质量。

**方案**:
- 在向量检索后增加交叉编码器重排序步骤
- 候选模型: `BAAI/bge-reranker-v2-m3`（本地运行）或 Cohere Rerank API
- 结合时间衰减因子: 最近记忆权重更高
- 注入时附带时间戳和置信度，让 LLM 自行判断权重

**预留接口**:
- `pipeline/memory_injector.py` → `MemoryInjector.set_reranker(reranker_fn: Callable)`
- `memory/semantic_search.py` → `search()` 返回结果包含 `score` 字段，供 reranker 输入
- `config.yaml` → `memory.reranker.enabled: bool`, `memory.reranker.model: str`

**触发条件**: 当用户反馈"AI 提到了不相关的事情"频率超过阈值时，优先实现。

---

### R2: 上下文保留脱敏 (Context-Aware Anonymization)

**问题**: 初期使用 UUID 占位符（如 `__REDACTED_xxx__`），LLM 丢失了语义上下文。例如"张三昨天和李四吃饭"变成"__REDACTED_1__ 昨天和 __REDACTED_2__ 吃饭"，LLM 无法理解两个实体的关系。

**方案**:
- 升级为上下文保留脱敏: "张三" → "张先生"、"13812345678" → "尾号1234"
- 需要 NER + 上下文理解能力（可用小模型或规则引擎）
- 保留实体关系图谱，脱敏后仍可推理

**预留接口**:
- `pipeline/cognitive_isolator.py` → `CognitiveIsolator.set_anonymization_strategy(strategy: str)`
  - `"uuid"` — 初期默认，UUID 占位符
  - `"contextual"` — 未来升级，上下文保留脱敏
- `pipeline/cognitive_isolator.py` → `AnonymizationStrategy` 抽象基类，`anonymize()` / `restore()` 方法对
- `config.yaml` → `privacy.anonymization_strategy: "uuid" | "contextual"`

**触发条件**: 当 LLM 回复质量因脱敏信息丢失明显下降时实现。

---

### R3: 多用户隔离 (Multi-User Isolation)

**问题**: 当前架构面向单用户桌面应用。未来若推出家庭版、团队版或 SaaS 版，需要用户间数据隔离。

**方案**:
- 认证层: JWT Token 携带 `user_id`
- 存储隔离:
  - LanceDB: 按 `user_id` 字段过滤（同表隔离）或按用户分目录（物理隔离）
  - SQLite: 所有表增加 `user_id` 列，查询时强制过滤
  - 文件系统: `data/{user_id}/vectors/`, `data/{user_id}/journals/`
- 隐私管道: `redaction_map` 按 `user_id` 隔离（当前已是会话级，天然隔离）

**预留接口**:
- `infrastructure/vector_db.py` → `get_connection(user_id: str = "default")` — 当前 user_id 固定为 "default"
- `infrastructure/db.py` → 所有查询函数签名包含 `user_id` 参数（当前默认 "default"）
- `domain/models.py` → `ChatMessage`、`Memory` 等模型包含 `user_id` 字段
- `core/security.py` → JWT 解析已包含 `user_id` 提取逻辑

**触发条件**: 产品确定推出多用户版本时实现。

---

### R4: LLM 输出 Schema 校验 (Output Validation)

**问题**: 部分 LLM（特别是开源小模型）可能输出格式错误的 tool_call（参数类型不对、缺少必填字段等），导致 ToolExecutor 崩溃。

**方案**:
- 在 ToolExecutor 前增加 JSON Schema 校验层
- 校验失败时自动构造修正提示，让 LLM 重试（类似 ReAct 循环）
- 最多重试 2 次，仍失败则返回用户友好的错误信息

**预留接口**:
- `kernel/tools/executor.py` → `ToolExecutor.set_validator(validator_fn: Callable)`
- `kernel/tools/protocol.py` → `SkillProtocol.parameters_schema()` 返回 JSON Schema
- 迁移 v2 `tool_executor.py` 时，保留 `execute()` 的 try/except 结构，便于插入校验

**触发条件**: 迁移 v2 ToolExecutor 时顺手加入基础校验；完整 ReAct 重试循环后续迭代。

---

### R5: Provider 重试 Jitter (Retry with Jitter)

**问题**: 多个请求同时遇到 Provider 故障时，指数退避会导致"惊群效应"——所有请求在相同时间点重试，再次压垮 Provider。

**方案**:
- 在现有指数退避基础上增加随机 jitter: `delay = base_delay * 2^attempt + random(0, base_delay)`
- 实现简单，迁移时直接改

**预留接口**:
- `kernel/providers/health.py` → `HealthTracker.calculate_backoff()` 函数签名已包含 `jitter` 参数
- 迁移 v2 `provider_health.py` 时直接实现

**触发条件**: Phase 1 迁移 Provider 层时一并完成（改动量小，不单独排期）。

---

## 十一、审计日志详细设计 (v1.1 新增)

### 11.1 Trace ID 全链路追踪

```
每个用户请求生成一个 trace_id (UUID v4)
    │
    ├─ API 网关层: 生成 trace_id，注入请求上下文
    ├─ 隐私管道: 每级记录 trace_id + 级别名 + 耗时
    ├─ LLM 内核: 记录 trace_id + 模型选择 + token 用量
    ├─ 工具执行: 记录 trace_id + 工具名 + 参数摘要 + 结果摘要
    ├─ Shell 沙箱: 记录 trace_id + 命令 + 审批结果 + 执行结果
    └─ 隐私恢复: 记录 trace_id + 恢复的占位符数量（不记录原始数据）
```

### 11.2 审计日志 Schema (SQLite: audit.db)

```sql
CREATE TABLE audit_log (
    id          TEXT PRIMARY KEY,       -- UUID
    trace_id    TEXT NOT NULL,          -- 请求级追踪 ID
    timestamp   TEXT NOT NULL,          -- ISO 8601
    level       TEXT NOT NULL,          -- info / warn / error / security
    component   TEXT NOT NULL,          -- pipeline.isolator / kernel.router / tools.shell / ...
    action      TEXT NOT NULL,          -- request_start / model_selected / tool_executed / shell_denied / ...
    detail      TEXT,                   -- JSON 结构化详情（脱敏后）
    duration_ms INTEGER,               -- 操作耗时
    user_id     TEXT DEFAULT 'default'  -- 预留多用户
);

CREATE INDEX idx_audit_trace ON audit_log(trace_id);
CREATE INDEX idx_audit_time ON audit_log(timestamp);
CREATE INDEX idx_audit_level ON audit_log(level);
```

### 11.3 日志轮转策略

- 默认保留 90 天审计日志
- 按月分区（通过 `timestamp` 范围查询）
- 自动清理: 启动时删除超过 90 天的记录
- 可配置: `config.yaml` → `audit.retention_days: 90`
- 安全级别日志（`level=security`）保留 1 年
