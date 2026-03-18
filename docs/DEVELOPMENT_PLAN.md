# eVoiceClaw Desktop v3 — 开发 + 开源准备集成计划

> 创建日期: 2026-03-09
> 状态: 执行中
> 核心理念: 边开发边准备开源，用 AI OS 自举验证自身能力

---

## 开发环境配置（必读）

### Python 虚拟环境

```bash
# 创建 venv（必须使用系统 Python 3.11，不要用 conda 或 3.12）
cd backend/
/usr/local/bin/python3.11 -m venv .venv

# 安装依赖（注意版本约束）
.venv/bin/pip install -r requirements.txt "numpy<2.0" "transformers<5.0" sentence-transformers
```

**已知版本约束**（2026-03-10 确认）：

| 包 | 约束 | 原因 |
|---|---|---|
| Python | **3.11.x** | torch 2.2.2 在 macOS x86_64 上不支持 3.12；3.12 的 venv 会指向 conda 导致 site-packages 路径不一致 |
| numpy | **< 2.0** | torch 2.2.2 不兼容 numpy 2.x（`NameError: name 'nn' is not defined`）|
| transformers | **< 5.0** | transformers 5.x 要求 torch >= 2.5，而 macOS x86_64 无 torch 2.5 预编译包 |
| sentence-transformers | 未锁定 | requirements.txt 中被注释掉了，但 `config.yaml` 使用 `provider: local` 需要它 |

**启动命令**：
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 28771
```

**常见问题**：
- `ModuleNotFoundError: No module named 'lancedb'` → venv 的 Python 版本与 pip 安装目标不一致，需重建 venv
- Embedding 模型首次加载需要下载 BAAI/bge-small-zh-v1.5（约 100MB），期间无法处理请求

---

## 总体策略

**一个核心，多套配置** — 开源一个版本，通过配置文件区分国内/国外/本地模型。

**开源范围**: 核心闭源（商业 APP），生态开源（AI OS 引擎 + 工具链 + Skill 生态）。

**许可证**: Apache 2.0

---

## 开发阶段与开源准备的融合

### 阶段 A: 开源基础设施（与 Phase 2 并行）

在开发 Phase 2 隐私管道的同时，完成开源发布的基础准备：

| 任务 | 说明 | 状态 |
|------|------|------|
| 创建 `config.example.cn.yaml` | 国内模型配置模板（DeepSeek/智谱/通义/Kimi） | ⏳ 待创建 |
| 创建 `config.example.us.yaml` | 国际模型配置模板（OpenAI/Anthropic/Gemini） | ⏳ 待创建 |
| 创建 `config.example.local.yaml` | 本地模型配置模板（Ollama/LM Studio） | ⏳ 待创建 |
| 创建 `secrets.yaml.example` | API Key 占位符模板 | ⏳ 待创建 |
| 补充 `.gitignore` | 确保 secrets.yaml 和运行时数据完全排除 | ✅ 已完成 |
| 创建 README.md（英文） | 项目介绍、快速启动、架构概览 | ⏳ 待创建 |
| 创建 CONTRIBUTING.md | 贡献者指南（Skill 开发、代码规范） | ⏳ 待创建 |
| 创建 LICENSE | Apache 2.0 许可证文件 | ⏳ 待创建 |

### 阶段 B: Phase 2 隐私管道（核心开发）

隐私管道是 AI OS 的核心差异化功能，按 ARCHITECTURE.md 第 4.1 节设计实现。

**开发顺序**（按数据流方向）:

| 序号 | 模块 | 文件 | 依赖 |
|------|------|------|------|
| ① | 认知隔离器 | `pipeline/cognitive_isolator.py` | 无外部依赖（正则+规则） |
| ② | 实体类别映射器 | `pipeline/entity_mapper.py` | LanceDB entities 表 + Embedding |
| ③ | 动态上下文压缩器 | `pipeline/context_compressor.py` | ① 的输出 |
| ④ | 记忆注入器 | `pipeline/memory_injector.py` | LanceDB memories 表 + Embedding |
| ⑤ | 记忆蒸馏器 | `pipeline/memory_distiller.py` | LLM + LanceDB distilled 表 |
| ⑥ | 管道编排器 | `pipeline/pipeline.py` | ①-⑤ 串联 |
| ⑦ | 隐私恢复器 | `pipeline/privacy_restorer.py` | redaction_map |
| ⑧ | 集成到 ChatService | `services/chat_service.py` 修改 | ⑥⑦ |

**每个模块完成后的验证**:
- 单元测试通过
- 在代码中标注 `# AI OS v3 Phase 2` 注释
- 更新 BACKLOG.md 和 CODEBASE_INDEX.md

### 阶段 C: 代码审核 Skill（Phase 2 完成后）

> 用户明确要求：代码审核排在隐私系统完成之后。

代码审核 Skill 是 AI OS 自举的第一个应用——用自己来审查自己。

**实现思路**:
1. 创建 `CodeReviewSkill`，作为内置 Skill 注册到 ToolRegistry
2. Skill 的审核提示词不硬编码，而是通过系统调用 R1（高推理模型）生成
3. 将开源策略文档（`docs/Open_source_self-verification.md`）作为 R1 上下文的一部分
4. 审核结果通过 commit message 和代码注释留下标记

**R1 生成审核提示词的流程**:
```
系统启动时:
  1. 读取 Open_source_self-verification.md 作为上下文
  2. 调用 R1（高推理模型）生成代码审核规则和提示词
  3. 缓存生成的提示词到本地

代码审核时:
  1. 读取缓存的审核提示词
  2. 对目标代码执行审核
  3. 输出结构化审核意见（severity + message + suggestion）
  4. 在 commit/PR 中留下 [AI reviewed] 标记
```

**依赖**:
- Phase 2 隐私管道（审核结果需经隐私处理）
- ToolRegistry（注册为内置工具）
- LLM Router（调用 R1 生成提示词）

### 阶段 D: Phase 3 Shell + 守门员（按原计划）

在代码审核 Skill 验证了自举模式后，继续按 BACKLOG 推进。

### 阶段 E: 开源发布准备（Phase 3 完成后）

| 任务 | 说明 |
|------|------|
| 代码安全审查 | 用代码审核 Skill 扫描全部代码 |
| 敏感信息清理 | 确保无 API Key、个人信息泄露 |
| 文档完善 | README、CONTRIBUTING、API 文档 |
| CI/CD 配置 | GitHub Actions（lint + test） |
| 创建 GitHub Organization | github.com/evoiceclaw |
| 首次发布 | v3.0.0-alpha tag |

---

## 多地区配置策略

**核心原则**: 代码完全一致，仅配置不同。

| 配置文件 | 目标用户 | 预配置模型 |
|---------|---------|-----------|
| `config.example.cn.yaml` | 国内开发者 | DeepSeek, 智谱GLM, 通义千问, Kimi, 百川 |
| `config.example.us.yaml` | 国际开发者 | OpenAI GPT-4o, Anthropic Claude, Google Gemini |
| `config.example.local.yaml` | 隐私敏感用户 | Ollama (Llama/Qwen), LM Studio |

---

## 自举验证体系

### 透明度机制

1. **commit 标记**: `[AI reviewed]` 或 `AI-assisted` 前缀
2. **meta/ 目录**: 存放 AI 审核记录、生成的文档初稿
3. **月度透明度报告**: 记录 AI OS 辅助完成了哪些任务

### 证据链

```
代码变更 → AI 审核（留标记） → 人工复核 → 合并
                ↓
         审核日志（audit.db）
                ↓
         月度透明度报告
```

---

## 当前执行优先级

1. **立即执行**: 创建配置模板文件（config.example.*.yaml, secrets.yaml.example）
2. **立即执行**: 创建 LICENSE (Apache 2.0)
3. **接下来**: 开始 Phase 2 隐私管道开发（从认知隔离器开始）
4. **Phase 2 完成后**: 代码审核 Skill + R1 提示词生成
5. **Phase 3 完成后**: 开源发布准备

---

## 变更记录

| 日期 | 变更内容 |
|------|---------|
| 2026-03-09 | 初始创建，融合开源准备与 Phase 2-5 开发计划 |
