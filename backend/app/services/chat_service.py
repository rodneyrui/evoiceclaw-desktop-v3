"""对话服务：管理多轮会话 + 调用 LLM Router 流式生成 + Tool 执行循环

Phase 2：集成隐私管道（认知隔离 + 实体映射 + 上下文压缩 + 记忆注入 + 记忆蒸馏 + 隐私恢复）。
数据流：用户消息 → 隐私管道 → LLM 流式 → 隐私恢复 → 用户。
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from app.domain.models import ChatMessage, StreamChunk, ToolCall, RedactionEntry, StreamChunkType, SessionPrivacyContext
from app.infrastructure import db as session_db
from app.kernel.router.llm_router import get_router
from app.kernel.router.smart_router import select_model_with_intent
from app.kernel.tools.registry import get_tool_registry
from app.kernel.tools.executor import ToolExecutor, MAX_TOOL_ROUNDS
from app.pipeline.pipeline import get_pipeline
from app.pipeline.context_compressor import estimate_tokens
from app.security.permission_broker import (
    ELEVATION_MARKER,
    elevation_level,
    get_permission_broker,
)
from app.kernel.context import ExecutionContext, execution_context
from app.services.model_alias import _detect_explicit_model
from app.services.url_processor import _enhance_message_with_urls
from app.services.stream_session import (
    StreamSession, start_stream_session, get_stream_recovery, _chunk_to_payload,
)

logger = logging.getLogger("evoiceclaw.chat")


def _get_active_workspace_id() -> str:
    """获取当前激活工作区的 ID，无激活工作区时返回 'global'。"""
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        active = ws_svc.get_active_workspace()
        if active:
            return active.id
    except Exception as e:
        logger.debug("[对话] 获取激活工作区失败: %s", e)
    return "global"


def _build_workspace_context() -> str:
    """构建工作区上下文信息，注入 system prompt 让 Agent 知道自己的工作区。

    包含：工作区名称、可写目录路径、Shell 安全级别、能力说明。
    优先引导 Agent 使用项目目录（用户可见位置），而非隐藏的元数据目录。
    无激活工作区时返回空字符串。
    """
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        active = ws_svc.get_active_workspace()
        if not active:
            return ""

        parts: list[str] = ["\n\n--- 工作区 ---"]
        parts.append(f"当前工作区：{active.name}")
        if active.description:
            parts.append(f"描述：{active.description}")

        # 项目目录（用户可见，优先写入目标）
        project_dir = active.path or ""
        if project_dir:
            parts.append(f"项目目录（主要写入位置）：{project_dir}")

        # 工作区数据目录（元数据/内部存储，备用）
        from app.kernel.tools.builtin.filesystem import _WORKSPACES_DIR
        workspace_data_dir = str(_WORKSPACES_DIR / active.id)
        parts.append(f"工作区数据目录（内部存储）：{workspace_data_dir}")

        # 能力说明
        parts.append("")
        parts.append("工作区权限：")
        if project_dir:
            parts.append(f"- 你可以在项目目录 {project_dir} 中自由创建、编辑文件（使用 write_file / edit_file 工具）")
            parts.append(f"- 创建文件时优先使用项目目录的绝对路径，如：{project_dir}/分析报告.md")
        parts.append("- 工作区数据目录也可写入，但建议优先使用项目目录（用户更容易找到文件）")
        parts.append("- 工作区外的文件只能读取，不能写入")

        # Shell 权限说明
        if active.shell_enabled:
            parts.append("")
            parts.append("Shell 权限（三层沙箱 L1/L2/L3）：")
            if project_dir:
                parts.append(f"- 工作区内（{project_dir}）：你可以自由执行代码（python3、node、git 等）和文件操作（mkdir、cp、rm 等），无需额外授权")
            parts.append("- 工作区外：仅允许只读命令（ls、cat、grep、curl GET 等）")
            parts.append("- L3 高权限操作（如涉及系统配置变更）：需要用户确认后才能执行")
            parts.append("- 绝对禁止的命令（sudo、ssh、chmod、kill 等系统管理命令）：任何级别都不允许")
            parts.append(f"- 当前基础级别：{active.shell_level}")
        else:
            parts.append("- Shell：未启用")

        parts.append("")
        parts.append("重要：当你需要保存工作成果（分析报告、收集的资料、代码等），必须使用 write_file 工具写入工作区目录，不要编造文件操作结果。")

        return "\n".join(parts)
    except Exception as e:
        logger.debug("[对话] 构建工作区上下文失败: %s", e)
        return ""


# ── 内存会话存储（Phase 1 简化方案，无持久化） ──

_conversations: dict[str, list[ChatMessage]] = {}
_conversation_ts: dict[str, float] = {}
_conv_lock = asyncio.Lock()
# 每会话的隐私上下文（贯穿整个对话生命周期）
_conversation_privacy_ctx: dict[str, SessionPrivacyContext] = {}

MAX_CONVERSATIONS = 100
CONVERSATION_TTL = 3600  # 1 小时

# ── 工具注册状态 ──
_tools_registered = False

def _persist_message(session_id: str, msg: ChatMessage, is_first_user: bool = False) -> None:
    """将消息持久化到 SQLite（非阻塞，失败不影响主流程）"""
    try:
        role_str = msg.role.value if hasattr(msg.role, "value") else msg.role

        # 序列化 tool_calls（assistant 消息携带工具调用）
        tool_calls_json = None
        if msg.tool_calls:
            import json
            tool_calls_json = json.dumps([
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ], ensure_ascii=False)

        session_db.insert_message(
            msg_id=msg.id,
            session_id=session_id,
            role=role_str,
            content=msg.content[:50000],  # 防止超长内容
            model=msg.model,
            tool_calls_json=tool_calls_json,
            tool_call_id=msg.tool_call_id,
            tool_name=msg.name,
        )
        session_db.touch_session(session_id)
        if is_first_user and role_str == "user":
            session_db.update_session_title(session_id, msg.content[:100])
    except Exception as e:
        logger.debug("[对话] 消息持久化失败（非关键）: %s", e)


def _truncate_tool_content(content: str, max_tokens: int = 8000) -> str:
    """截断超长 tool 结果，防止单条结果撑爆上下文"""
    tokens = estimate_tokens(content)
    if tokens <= max_tokens:
        return content
    # 按字符比例截断
    ratio = max_tokens / tokens
    cut_len = int(len(content) * ratio * 0.9)  # 留 10% 余量
    return content[:cut_len] + "\n\n[已截断：原始内容过长，已保留前部分]"


# ── 快速路径关键词 ──
_GREETING_KEYWORDS = frozenset([
    "你好", "您好", "嗨", "hi", "hello", "hey",
    "在吗", "在不在", "在么",
    "谢谢", "感谢", "多谢", "thanks", "thank",
    "再见", "拜拜", "bye", "晚安", "早安", "早上好", "下午好", "晚上好",
    "好的", "ok", "嗯", "哦", "哈喽",
])


def _is_fast_path(message: str) -> bool:
    """判断消息是否命中快速路径（简单问候/告别）"""
    text = message.strip().lower()
    if len(text) <= 10 and text in _GREETING_KEYWORDS:
        return True
    if text.startswith("/"):
        return True
    return False


def _find_tool_capable_fallback(original_model_id: str, config: dict) -> str | None:
    """为 no-tools 模型找一个同 provider 下支持工具的替代模型

    优先同 provider，找不到再跨 provider。
    """
    from app.kernel.providers.api_provider import _NO_TOOLS_MODELS

    original_provider = original_model_id.split("/", 1)[0] if "/" in original_model_id else ""
    providers = config.get("providers", {})

    def _scan_provider(pid: str, pcfg: dict) -> str | None:
        if not pcfg.get("enabled") or not pcfg.get("api_key"):
            return None
        for m in pcfg.get("models", []):
            mid = m if isinstance(m, str) else (m.get("id", "") if isinstance(m, dict) else "")
            if not mid:
                continue
            full_id = mid if "/" in mid else f"{pid}/{mid}"
            model_name = mid.rsplit("/", 1)[-1]
            if model_name not in _NO_TOOLS_MODELS:
                return full_id
        return None

    # 优先同 provider
    if original_provider and original_provider in providers:
        result = _scan_provider(original_provider, providers[original_provider])
        if result:
            return result

    # 跨 provider
    for pid, pcfg in providers.items():
        if pid == original_provider:
            continue
        result = _scan_provider(pid, pcfg)
        if result:
            return result

    return None


async def _cleanup_expired() -> None:
    """清理过期会话，过期前触发记忆蒸馏"""
    async with _conv_lock:
        now = time.time()
        expired = [
            cid for cid, ts in _conversation_ts.items()
            if now - ts > CONVERSATION_TTL
        ]
        for cid in expired:
            # 会话过期时触发记忆蒸馏（后台执行，不阻塞）
            msgs = _conversations.get(cid, [])
            if msgs:
                asyncio.create_task(_distill_on_expire(cid, msgs))
            _conversations.pop(cid, None)
            _conversation_ts.pop(cid, None)
            _conversation_privacy_ctx.pop(cid, None)

        # 超出上限时移除最旧的
        if len(_conversations) > MAX_CONVERSATIONS:
            sorted_items = sorted(_conversation_ts.items(), key=lambda x: x[1])
            to_remove = len(_conversations) - MAX_CONVERSATIONS
            for cid, _ in sorted_items[:to_remove]:
                msgs = _conversations.get(cid, [])
                if msgs:
                    asyncio.create_task(_distill_on_expire(cid, msgs))
                _conversations.pop(cid, None)
                _conversation_ts.pop(cid, None)
                _conversation_privacy_ctx.pop(cid, None)


async def _distill_on_expire(conversation_id: str, messages: list[ChatMessage]) -> None:
    """会话过期时异步执行记忆蒸馏（⑤ 级管道）"""
    try:
        pipeline = get_pipeline()
        await pipeline.distill_session(messages, conversation_id)
    except Exception as e:
        logger.debug("[对话] 过期蒸馏跳过: conv=%s %s", conversation_id, e)


def register_builtin_tools() -> None:
    """注册所有内置工具到 ToolRegistry（由 lifespan 调用，幂等）"""
    global _tools_registered
    if _tools_registered:
        return

    registry = get_tool_registry()

    # ── 网络工具 ──
    from app.kernel.tools.builtin.network import HttpRequestTool
    from app.kernel.tools.builtin.web_search import WebSearchTool
    from app.kernel.tools.builtin.web_fetch import WebFetchTool
    registry.register(HttpRequestTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())

    # ── 文件系统工具 ──
    from app.kernel.tools.builtin.filesystem import ReadFileTool, ListDirectoryTool, WriteFileTool
    registry.register(ReadFileTool())
    registry.register(ListDirectoryTool())
    registry.register(WriteFileTool())

    # ── 数据库查询工具 ──
    from app.kernel.tools.builtin.database import QueryDatabaseTool
    registry.register(QueryDatabaseTool())

    # ── Shell 沙箱工具（Phase 3） ──
    from app.kernel.tools.builtin.shell import ExecCommandTool
    registry.register(ExecCommandTool())

    # ── 文件编辑工具 ──
    from app.kernel.tools.builtin.filesystem import EditFileTool
    registry.register(EditFileTool())

    # ── PDF 读取工具 ──
    from app.kernel.tools.builtin.pdf_reader import ReadPdfTool
    registry.register(ReadPdfTool())

    # ── 记忆操作工具 ──
    from app.kernel.tools.builtin.memory_ops import MemoryOpsTool
    registry.register(MemoryOpsTool())

    # ── 代码审核工具 ──
    from app.kernel.tools.builtin.code_review import CodeReviewTool
    registry.register(CodeReviewTool())

    # ── 工作区管理工具 ──
    from app.kernel.tools.builtin.workspace import WorkspaceMgmtTool
    registry.register(WorkspaceMgmtTool())

    # ── Skill 管理工具 ──
    from app.kernel.tools.builtin.skill_mgmt import SkillMgmtTool
    registry.register(SkillMgmtTool())

    # ── AI 标记工具（宪法第25条） ──
    from app.kernel.tools.builtin.ai_marker import AiMarkerTool
    registry.register(AiMarkerTool())

    # ── 专家咨询工具（Multi-Agent 协作） ──
    from app.kernel.tools.builtin.consult_expert import ConsultExpertTool
    registry.register(ConsultExpertTool())

    # Phase 4+: browser（需 Playwright）

    _tools_registered = True
    logger.info("[对话] 工具注册完成: %d 个工具", len(registry.get_all()))


async def chat_stream(
    message: str,
    model_id: str,
    config: dict,
    conversation_id: str | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[StreamChunk, None]:
    """流式对话入口

    Args:
        message: 用户消息
        model_id: 模型标识（如 "deepseek/deepseek-chat" 或 "cli:claude" 或 "auto"）
        config: 全局配置
        conversation_id: 会话 ID（可选，用于多轮对话）
        system_prompt: 系统提示词（可选，仅首次消息生效）

    Yields:
        StreamChunk 流式输出块
    """
    await _cleanup_expired()

    # 自然语言模型指定：检测消息中是否显式指定了模型（优先级高于自动路由）
    explicit_model, message = _detect_explicit_model(message, config)

    # 智能路由：model_id="auto" 时自动选择最优模型
    intent: str | None = None
    actual_model_id = model_id
    fallback_candidates: list[str] = []
    if explicit_model:
        actual_model_id = explicit_model
        logger.info("[对话] 用户显式指定模型: %s", actual_model_id)
    elif model_id == "auto":
        actual_model_id, intent, fallback_candidates = await select_model_with_intent(message, config)
        if not actual_model_id:
            yield StreamChunk(type="error", content="自动路由失败：无可用模型")
            return
        logger.info("[对话] 自动路由: auto → %s (意图=%s)", actual_model_id, intent)

    # 快速路径标记
    light_context = _is_fast_path(message)

    # URL 预处理：检测并抓取链接内容（快速路径跳过）
    detected_urls: list[str] = []
    enhanced_message = message
    if not light_context:
        enhanced_message, detected_urls = await _enhance_message_with_urls(message)
        if detected_urls:
            # 通知前端检测到了 URL
            yield StreamChunk(type="url_detected", content=",".join(detected_urls))

    # ── 隐私管道：输入处理（①②③④ 级） ──
    pipeline_result = None
    redaction_map: dict[str, RedactionEntry] = {}
    memory_text = ""
    # 获取当前激活工作区 ID（服务层自行获取，不依赖前端传入）
    workspace_id = _get_active_workspace_id()
    # 获取或创建会话级隐私上下文
    privacy_ctx = _conversation_privacy_ctx.get(conversation_id) if conversation_id else None
    if not light_context:
        try:
            pipeline = get_pipeline()
            # 获取当前会话的历史消息用于压缩
            existing_messages = _conversations.get(conversation_id, []) if conversation_id else []
            pipeline_result = await pipeline.process_input(
                message=enhanced_message,
                messages=existing_messages,
                user_id="default",
                workspace_id=workspace_id,
                model_id=actual_model_id,
            )
            enhanced_message = pipeline_result.clean_message
            redaction_map = pipeline_result.redaction_map
            memory_text = pipeline_result.memory_text

            # 合并到会话级隐私上下文（多轮会话中 LLM 可能在后续轮次引用占位符）
            if conversation_id and redaction_map:
                if privacy_ctx is None:
                    privacy_ctx = SessionPrivacyContext()
                privacy_ctx.merge_redaction(redaction_map)
                _conversation_privacy_ctx[conversation_id] = privacy_ctx
                redaction_map = privacy_ctx.redaction_map

            if pipeline_result.redaction_map:
                logger.info(
                    "[对话] 隐私管道: 隔离=%s 实体=%d 记忆=%d trace=%s",
                    pipeline_result.isolation_stats,
                    pipeline_result.entity_count,
                    pipeline_result.memory_count,
                    pipeline_result.trace_id,
                )
        except RuntimeError:
            # Pipeline 未初始化（如未启用隐私功能），跳过
            pass
        except Exception as e:
            strict_mode = config.get("privacy", {}).get("strict_mode", True)
            if strict_mode:
                logger.error("[对话] 隐私管道处理失败（严格模式，拒绝请求）: %s", e)
                yield StreamChunk(type="error", content="隐私保护处理失败，请稍后重试。")
                return
            logger.warning("[对话] 隐私管道处理失败，降级为原始消息: %s", e)

    # ── 快速路径记忆补充 ──
    # 管道被跳过（快速路径/管道失败）但即将创建新会话时，仍做轻量记忆注入
    # L1 仅为 LanceDB filter 查询（无 embedding 开销，微秒级）
    if not memory_text:
        _is_new_conv = not conversation_id or conversation_id not in _conversations
        if _is_new_conv:
            try:
                from app.pipeline.memory_injector import MemoryInjector
                _fallback_result = await MemoryInjector({}).inject(
                    query="",  # 空查询 → 仅 L1（filter-only，无需 embedding）
                    workspace_id=workspace_id,
                )
                memory_text = _fallback_result.memory_text
                if memory_text:
                    logger.info("[对话] 快速路径记忆补充: %d 条", len(_fallback_result.memories))
            except Exception as e:
                logger.debug("[对话] 记忆补充注入跳过: %s", e)

    # 获取或创建会话
    is_new_session = False
    is_first_user_msg = False
    async with _conv_lock:
        if conversation_id and conversation_id in _conversations:
            messages = _conversations[conversation_id]
        else:
            conversation_id = conversation_id or str(uuid.uuid4())
            messages = []

            # 冷启动恢复：内存中没有但 DB 中有历史消息
            if conversation_id:
                db_msgs = session_db.load_session_messages(conversation_id, limit=200)
                if db_msgs:
                    for row in db_msgs:
                        # 反序列化 tool_calls
                        tool_calls = None
                        tc_json = row.get("tool_calls_json")
                        if tc_json:
                            try:
                                import json
                                from app.domain.models import ToolCall
                                tc_list = json.loads(tc_json)
                                tool_calls = [
                                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                                    for tc in tc_list
                                ]
                            except Exception:
                                logger.debug("[对话] 冷启动: tool_calls 反序列化失败，跳过")

                        messages.append(ChatMessage(
                            id=row["id"],
                            role=row["role"],
                            content=row["content"],
                            model=row.get("model"),
                            tool_calls=tool_calls,
                            tool_call_id=row.get("tool_call_id"),
                            name=row.get("tool_name"),
                            created_at=row.get("created_at", ""),
                        ))

                    # 清理旧数据中损坏的工具消息：
                    # - tool 角色消息缺少 tool_call_id → 剥离
                    # - assistant 消息内容为空且无 tool_calls → 剥离
                    cleaned = []
                    for m in messages:
                        role_val = m.role.value if hasattr(m.role, "value") else m.role
                        if role_val == "tool" and not m.tool_call_id:
                            logger.debug("[对话] 冷启动清理: 剥离缺少 tool_call_id 的 tool 消息 id=%s", m.id)
                            continue
                        if role_val == "assistant" and not m.content.strip() and not m.tool_calls:
                            logger.debug("[对话] 冷启动清理: 剥离空 assistant 消息 id=%s", m.id)
                            continue
                        cleaned.append(m)
                    if len(cleaned) < len(messages):
                        logger.info(
                            "[对话] 冷启动清理: 剥离 %d 条损坏的工具消息",
                            len(messages) - len(cleaned),
                        )
                    messages = cleaned

                    _conversations[conversation_id] = messages
                    _conversation_ts[conversation_id] = time.time()
                    logger.info(
                        "[对话] 冷启动恢复: conv=%s 从 DB 加载 %d 条消息",
                        conversation_id, len(messages),
                    )

            is_new_session = len(messages) == 0

            if is_new_session:
                # 构建 system prompt
                if not system_prompt:
                    system_prompt = _build_default_system_prompt(config)

                # 行为准则注入（最高优先级，放在 system prompt 最前面）
                agent_backstory = config.get("agent", {}).get("backstory", "")
                if agent_backstory:
                    system_prompt = "--- 行为准则（最高优先级）---\n" + agent_backstory.strip() + "\n\n" + (system_prompt or "")

                # 规则引擎生成的 per-model 行为规则注入
                # model_prompts.yaml 中每个模型有独立的 system_prompt（优势/限制/方法论）
                model_behavior = _load_model_behavior(actual_model_id)
                if model_behavior:
                    system_prompt = (system_prompt or "") + "\n\n--- 模型行为规则（规则引擎生成）---\n" + model_behavior
                    logger.info("[对话] 行为规则注入: model=%s", actual_model_id)

                # 当前时间注入
                now = datetime.now()
                weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
                time_info = f"\n\n--- 当前时间 ---\n{now.strftime('%Y年%m月%d日 %H:%M')} {weekday_cn}"
                system_prompt = (system_prompt or "") + time_info

                # 工具能力声明注入（快速路径跳过）
                if not light_context:
                    tool_registry = get_tool_registry()
                    capability_decl = tool_registry.build_capability_declaration()
                    if capability_decl:
                        system_prompt = system_prompt + capability_decl

                # 工作区上下文注入：告知 Agent 当前工作区路径和权限
                workspace_ctx = _build_workspace_context()
                if workspace_ctx:
                    system_prompt = system_prompt + workspace_ctx

                # 记忆文本注入（隐私管道 ④ 级输出）
                if memory_text:
                    system_prompt = system_prompt + memory_text

                if system_prompt:
                    messages.append(ChatMessage(role="system", content=system_prompt))
                _conversations[conversation_id] = messages

                # DB 持久化：创建会话记录
                session_db.create_session(conversation_id, title="", user_id="default")

        # 判断是否为该会话的首条用户消息（用于设置标题）
        user_msg_count = sum(1 for m in messages if (m.role.value if hasattr(m.role, "value") else m.role) == "user")
        is_first_user_msg = user_msg_count == 0

        # 追加用户消息（如果有 URL 则使用增强版本）
        user_msg = ChatMessage(role="user", content=enhanced_message)
        messages.append(user_msg)
        _conversation_ts[conversation_id] = time.time()

        # DB 持久化：写入用户消息
        _persist_message(conversation_id, user_msg, is_first_user=is_first_user_msg)

    # 隐私提醒注入：让 LLM 在回复中自然告知用户隐私保护已启用
    if privacy_ctx and privacy_ctx.privacy_notice:
        messages.append(ChatMessage(
            role="system",
            content=privacy_ctx.privacy_notice,
        ))
        privacy_ctx.privacy_notice = None  # 一次性，用完清空

    logger.info(
        "[对话] model=%s conv=%s 历史消息数=%d",
        actual_model_id, conversation_id, len(messages),
    )

    # 准备工具
    tool_registry = get_tool_registry()
    executor = ToolExecutor(tool_registry)
    tools_json = None
    if not light_context and not actual_model_id.startswith("cli:"):
        tools_json = tool_registry.tools_json_for_llm()
        if not tools_json:
            tools_json = None  # 空列表时不传

    # no-tools 模型自动降级（如 deepseek-reasoner 不支持 function calling）
    if tools_json:
        from app.kernel.providers.api_provider import _NO_TOOLS_MODELS
        _mn = actual_model_id.split("/", 1)[-1] if "/" in actual_model_id else actual_model_id
        if _mn in _NO_TOOLS_MODELS:
            _fallback = _find_tool_capable_fallback(actual_model_id, config)
            if _fallback:
                logger.info(
                    "[对话] %s 不支持工具调用，自动降级到 %s",
                    actual_model_id, _fallback,
                )
                yield StreamChunk(
                    type="status",
                    content=f"{actual_model_id} 为纯推理模型，不支持文件读取等工具。已自动切换到 {_fallback}。",
                )
                actual_model_id = _fallback
            else:
                # 无替代模型，清空工具避免模型输出伪代码
                tools_json = None
                logger.warning(
                    "[对话] %s 不支持工具且无替代模型，本次禁用工具",
                    actual_model_id,
                )

    # 流式生成 + 工具执行循环
    router = get_router()
    # 追踪本轮对话所有工具调用名（用于验证触发判断）
    tool_names_used: list[str] = []

    # 构建发给 LLM 的消息列表：优先使用压缩后的版本
    # 内存 messages 保留完整历史（用于持久化和蒸馏），LLM 只看压缩版
    llm_messages = messages  # 默认使用完整历史
    if pipeline_result and pipeline_result.compressed_messages:
        # compressed_messages 不含当前用户消息，需追加
        llm_messages = list(pipeline_result.compressed_messages) + [messages[-1]]
        logger.info(
            "[对话] 使用压缩消息: 原始=%d → 压缩=%d",
            len(messages), len(llm_messages),
        )

    # auto 模式：复用首次路由返回的候选列表，用于 fallback
    use_fallback = model_id == "auto" and not explicit_model
    # fallback_candidates 已在上方 select_model_with_intent 中获取
    if use_fallback and not fallback_candidates:
        fallback_candidates = []

    # 上下文超限自动缩减重试计数
    _context_retry_count = 0
    _MAX_CONTEXT_RETRIES = 2

    # ── 设置根执行上下文（递归保护） ──
    root_ctx = ExecutionContext(parent_model_id=actual_model_id)
    ctx_token = execution_context.set(root_ctx)

    for round_idx in range(MAX_TOOL_ROUNDS):
        pending_tool_calls: list[ToolCall] = []
        assistant_parts: list[str] = []
        end_chunk: StreamChunk | None = None
        round_reasoning_content: str = ""

        # auto 模式且有候选列表 → stream_with_fallback；否则 → 单模型 stream
        if use_fallback and fallback_candidates:
            stream_source = router.stream_with_fallback(
                llm_messages, fallback_candidates, config, tools=tools_json,
            )
        else:
            stream_source = router.stream(llm_messages, actual_model_id, config, tools=tools_json)

        async for chunk in stream_source:
            if chunk.type == "text":
                assistant_parts.append(chunk.content)
                # 隐私恢复：替换 LLM 输出中的占位符
                if redaction_map:
                    restored_content = _restore_chunk(chunk.content, redaction_map)
                    yield StreamChunk(type="text", content=restored_content)
                else:
                    yield chunk
            elif chunk.type == "tool_call":
                pending_tool_calls.append(chunk.tool_call)
                yield chunk
            elif chunk.type == "end":
                if chunk.reasoning_content:
                    round_reasoning_content = chunk.reasoning_content
                if not pending_tool_calls:
                    end_chunk = chunk
            elif chunk.type == "error":
                # 检测上下文窗口超限错误，自动缩减重试
                from app.kernel.router.llm_router import CONTEXT_EXCEEDED_KEYWORDS
                error_lower = chunk.content.lower()
                if (
                    _context_retry_count < _MAX_CONTEXT_RETRIES
                    and any(kw in error_lower for kw in CONTEXT_EXCEEDED_KEYWORDS)
                ):
                    _context_retry_count += 1
                    # 砍掉前 1/3 非 system 消息
                    non_sys = [i for i, m in enumerate(llm_messages)
                               if (m.role.value if hasattr(m.role, "value") else m.role) != "system"]
                    cut_count = max(1, len(non_sys) // 3)
                    indices_to_remove = set(non_sys[:cut_count])
                    llm_messages = [m for i, m in enumerate(llm_messages) if i not in indices_to_remove]
                    yield StreamChunk(
                        type="status",
                        content=f"[上下文超限] 自动缩减历史消息，重试中（{_context_retry_count}/{_MAX_CONTEXT_RETRIES}）...",
                    )
                    logger.warning(
                        "[对话] 上下文超限重试 %d/%d: 砍掉 %d 条消息，剩余 %d 条",
                        _context_retry_count, _MAX_CONTEXT_RETRIES, cut_count, len(llm_messages),
                    )
                    break  # break 内层 stream loop，外层 for 会重新进入
                yield chunk
                break
            else:
                yield chunk  # thinking 等其他类型原样传递

        if not pending_tool_calls:
            # 无工具调用，保存回复
            if assistant_parts:
                full_reply = "".join(assistant_parts)
                # 隐私恢复：完整回复做一次兜底恢复后再存入历史
                if redaction_map:
                    try:
                        pipeline = get_pipeline()
                        full_reply = pipeline.restore_output(full_reply, redaction_map)
                    except Exception as e:
                        logger.warning("[对话] 隐私恢复失败，使用原始回复: %s", e)
                # ── 回复验证（Phase 6.5）──
                try:
                    from app.services.verification_service import (
                        should_verify, verify_response, correct_response,
                        has_multiple_api_providers,
                    )
                    v_cfg = config.get("verification", {})
                    if v_cfg.get("enabled", True) and has_multiple_api_providers(config):
                        need_verify, v_method = should_verify(
                            message, full_reply, tool_names_used,
                            model_id=actual_model_id, intent=intent,
                            config=config,
                        )
                        if need_verify:
                            v_result = await verify_response(
                                message, full_reply, config,
                                method=v_method, model_id=actual_model_id, intent=intent,
                            )
                            if v_result:
                                from app.security.audit import log_event, LEVEL_INFO, LEVEL_WARN
                                log_event(
                                    component="verification",
                                    action="VERIFICATION_PASSED" if v_result.verified else "VERIFICATION_FAILED",
                                    trace_id=conversation_id,
                                    level=LEVEL_INFO if v_result.verified else LEVEL_WARN,
                                    detail=json.dumps({
                                        "method": v_method,
                                        "confidence": v_result.confidence,
                                        "issues": v_result.issues,
                                        "elapsed_ms": v_result.elapsed_ms,
                                    }),
                                )
                                corrected = None
                                if (
                                    not v_result.verified
                                    and v_cfg.get("auto_correct", True)
                                    and v_result.issues
                                ):
                                    corrected = await correct_response(
                                        message, full_reply, v_result.issues,
                                        actual_model_id, config,
                                    )
                                    if corrected:
                                        full_reply = corrected
                                yield StreamChunk(
                                    type=StreamChunkType.VERIFICATION_RESULT,
                                    content=json.dumps({
                                        "status": "corrected" if corrected else (
                                            "passed" if v_result.verified else "warning"
                                        ),
                                        "confidence": v_result.confidence,
                                        "issues": v_result.issues,
                                        "summary": v_result.summary,
                                        "corrected_content": corrected,
                                        "method": v_method,
                                    }, ensure_ascii=False),
                                )
                except Exception as _ve:
                    logger.debug("[对话] 回复验证失败（非关键，已跳过）: %s", _ve)
                messages.append(ChatMessage(role="assistant", content=full_reply))
                # DB 持久化：写入 assistant 回复
                _persist_message(conversation_id, messages[-1])
                logger.info(
                    "[对话] 完成: conv=%s 回复长度=%d",
                    conversation_id, len(full_reply),
                )
            if end_chunk:
                yield end_chunk
            # ── 对话轮次计数（Phase 7D 使用量触发）──
            _notify_conversation_turn()
            break

        # 有工具调用：追加 assistant 消息（带 tool_calls）到历史
        assistant_text = "".join(assistant_parts)
        assistant_tc_msg = ChatMessage(
            role="assistant",
            content=assistant_text,
            tool_calls=pending_tool_calls,
            reasoning_content=round_reasoning_content or None,
        )
        messages.append(assistant_tc_msg)
        # DB 持久化：写入带工具调用的 assistant 消息
        _persist_message(conversation_id, assistant_tc_msg)

        # 工具调用参数隐私恢复：将 LLM 生成的占位符还原为原始值（如文件路径中的人名）
        if redaction_map:
            try:
                pipeline = get_pipeline()
                for tc in pending_tool_calls:
                    tc.arguments = {
                        k: pipeline.restore_output(v, redaction_map) if isinstance(v, str) else v
                        for k, v in tc.arguments.items()
                    }
            except Exception as e:
                logger.warning("[对话] 工具参数隐私恢复失败: %s", e)

        # 执行每个 tool call（含权限协商）
        results = await executor.execute_all(pending_tool_calls, workspace_id=workspace_id)
        for i, (tc_id, result) in enumerate(results):
            tc = pending_tool_calls[i]
            tool_names_used.append(tc.name)

            # 检测是否为权限提升请求（而非普通工具结果）
            if _is_elevation_request(result):
                import json as _json
                elevation_data = _json.loads(result)
                required_level = elevation_data["required_level"]
                current_level = elevation_data["current_level"]
                cmd_name = elevation_data["cmd_name"]
                command = elevation_data["command"]

                if required_level == "L2":
                    # L1 → L2：自动提升，仅通知用户（不弹窗）
                    logger.info(
                        "[对话] 安全级别自动提升 %s → %s (cmd=%s)",
                        current_level, required_level, cmd_name,
                    )
                    yield StreamChunk(
                        type="text",
                        content=f"\n[安全通知] 已自动提升到 {required_level} 级别执行: {cmd_name}\n",
                    )
                    token = elevation_level.set(required_level)
                    try:
                        _, result = await executor.execute(tc, workspace_id=workspace_id)
                    finally:
                        elevation_level.reset(token)
                    logger.info("[对话] L2 自动提升执行成功: %s", cmd_name)
                else:
                    # L2 → L3 或更高：需要用户明确确认
                    broker = get_permission_broker()
                    req = broker.create_request(
                        command=command,
                        cmd_name=cmd_name,
                        current_level=current_level,
                        required_level=required_level,
                        reason=elevation_data["reason"],
                    )

                    # 向前端发送权限请求事件（弹窗确认）
                    yield StreamChunk(
                        type="permission_request",
                        content=_json.dumps({
                            "request_id": req.request_id,
                            "command": req.command,
                            "cmd_name": req.cmd_name,
                            "current_level": req.current_level,
                            "required_level": req.required_level,
                            "reason": req.reason,
                        }, ensure_ascii=False),
                    )

                    logger.info(
                        "[对话] 权限协商: 等待用户批准 %s → %s (cmd=%s)",
                        req.current_level, req.required_level, req.cmd_name,
                    )

                    # 等待用户决策（最长 120 秒）
                    approved = await broker.wait_for_decision(req.request_id, timeout=120)

                    if approved:
                        token = elevation_level.set(req.required_level)
                        try:
                            _, result = await executor.execute(tc, workspace_id=workspace_id)
                        finally:
                            elevation_level.reset(token)
                        logger.info("[对话] 权限提升后重新执行成功: %s", tc.name)
                    else:
                        result = f"用户拒绝了权限提升请求（{req.cmd_name} 需要 {req.required_level} 级别）"
                        logger.info("[对话] 权限提升被用户拒绝: %s", req.cmd_name)

            # ── 工具返回内容过隔离器（仅限读取用户本地文件的工具） ──
            # 搜索、网络请求等返回公开信息，不应脱敏；
            # 只有 read_file/read_pdf 读取用户私人文件时才需要保护个人信息
            _TOOLS_NEED_ISOLATION = {"read_file", "read_pdf"}
            clean_result = result
            if tc.name in _TOOLS_NEED_ISOLATION and not _is_elevation_request(result):
                try:
                    pipeline = get_pipeline()
                    tool_isolation = pipeline.isolator.isolate(result)
                    if tool_isolation.redaction_map:
                        clean_result = tool_isolation.clean_text
                        # 合并到会话级隐私上下文
                        if privacy_ctx is None:
                            privacy_ctx = SessionPrivacyContext()
                        privacy_ctx.merge_redaction(tool_isolation.redaction_map)
                        if conversation_id:
                            _conversation_privacy_ctx[conversation_id] = privacy_ctx
                        redaction_map = privacy_ctx.redaction_map
                        logger.info(
                            "[对话] 工具返回隔离: tool=%s 检测=%s",
                            tc.name, tool_isolation.stats,
                        )
                except RuntimeError:
                    pass  # Pipeline 未初始化
                except Exception as e:
                    logger.warning("[对话] 工具返回隔离失败，降级为原始结果: %s", e)

            # 若工具结果经过脱敏，附加隐私提示，告知 LLM 占位符会在用户侧还原
            tool_content = clean_result
            if clean_result != result:
                tool_content = (
                    clean_result
                    + "\n\n[系统提示] 以上内容中的占位符（__REDACTED_xxx__）在用户侧会自动还原为原始值。"
                    "请直接基于内容回答用户的问题，不要向用户提及脱敏、占位符或隐私处理。"
                    "如果用户询问的信息被占位符替代了，请正常引用占位符，系统会自动还原。"
                )

            # Step 5: 截断超长 tool 结果，防止撑爆上下文
            tool_content = _truncate_tool_content(tool_content)

            tool_msg = ChatMessage(
                role="tool",
                content=tool_content,
                tool_call_id=tc_id,
                name=tc.name,
            )
            messages.append(tool_msg)
            # DB 持久化：写入 tool 结果
            _persist_message(conversation_id, tool_msg)

            # ── 托管浏览器：web_fetch/http_request 成功后自动打开浏览器 ──
            if tc.name in ("web_fetch", "http_request") and not result.startswith("错误："):
                _browse_url = tc.arguments.get("url", "")
                if _browse_url:
                    from app.services.browser_service import get_browser_service
                    _bs = get_browser_service()
                    if _bs and _bs.open_url(_browse_url):
                        yield StreamChunk(
                            type=StreamChunkType.BROWSER_OPENED,
                            content=_browse_url,
                        )

            yield StreamChunk(
                type="tool_result",
                content=result,  # 前端展示原始结果（本地显示，不经过云端）
            )

        logger.info(
            "[对话] 工具轮次 %d: %d 个工具调用已执行",
            round_idx + 1, len(pending_tool_calls),
        )

        # 工具轮次后，llm_messages 同步为完整 messages（工具结果需要完整传递）
        llm_messages = messages

    else:
        # 达到 MAX_TOOL_ROUNDS 上限，强制总结
        logger.warning(
            "[对话] 达到工具调用上限 (%d 轮): conv=%s",
            MAX_TOOL_ROUNDS, conversation_id,
        )
        messages.append(ChatMessage(
            role="user",
            content=(
                "（系统提示：你已达到工具调用次数上限，无法再调用任何工具。"
                "请根据目前已获取到的信息，直接给出完整的回答。）"
            ),
        ))
        async for chunk in router.stream(llm_messages, actual_model_id, config, tools=None):
            if chunk.type == "text":
                yield chunk
            elif chunk.type == "end":
                yield chunk
        # ── 对话轮次计数（Phase 7D 使用量触发）──
        _notify_conversation_turn()

    # ── 清理根执行上下文 ──
    execution_context.reset(ctx_token)
def _build_default_system_prompt(config: dict) -> str:
    """构建默认系统提示词

    优先从 agent_personalities.yaml 的 agent_persona.system_prompt 加载；
    如果文件不存在或字段缺失，使用内置默认值。
    """
    # 尝试从规则引擎生成的人格文件加载完整 system prompt
    try:
        from pathlib import Path
        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "generated_rules"
        persona_path = rules_dir / "agent_personalities.yaml"
        if persona_path.exists():
            import yaml
            with open(persona_path, "r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f)
            if isinstance(parsed, dict):
                persona_prompt = (parsed.get("agent_persona") or {}).get("system_prompt", "")
                if persona_prompt and len(persona_prompt) > 50:
                    logger.info("[对话] 从 agent_personalities.yaml 加载完整人格 system_prompt")
                    return persona_prompt.strip()
    except Exception as e:
        logger.debug("[对话] 加载人格文件失败（降级为默认）: %s", e)

    # 默认精简版
    soul_name = config.get("services", {}).get("soul", {}).get("name", "小V")
    return (
        f"你是{soul_name}，一个智能助手。\n"
        "你可以通过 function calling 调用工具来完成任务。\n"
        "请用中文回复用户。"
    )


# 缓存 model_prompts.yaml 的解析结果（文件级缓存，避免每次对话都读磁盘）
_model_prompts_cache: dict | None = None
_model_prompts_mtime: float = 0.0


def _load_model_behavior(model_id: str) -> str | None:
    """从 model_prompts.yaml 加载指定模型的行为规则 system_prompt

    带文件级缓存：只在文件 mtime 变化时重新加载。
    """
    global _model_prompts_cache, _model_prompts_mtime

    try:
        from pathlib import Path
        rules_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "generated_rules"
        prompts_path = rules_dir / "model_prompts.yaml"
        if not prompts_path.exists():
            return None

        current_mtime = prompts_path.stat().st_mtime
        if _model_prompts_cache is None or current_mtime != _model_prompts_mtime:
            import yaml
            with open(prompts_path, "r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f)
            _model_prompts_cache = parsed.get("models", {}) if isinstance(parsed, dict) else {}
            _model_prompts_mtime = current_mtime
            logger.info("[对话] model_prompts.yaml 已加载/刷新，模型数: %d", len(_model_prompts_cache))

        model_config = _model_prompts_cache.get(model_id)
        if not model_config or not isinstance(model_config, dict):
            return None

        return model_config.get("system_prompt", "").strip() or None

    except Exception as e:
        logger.debug("[对话] 加载 model_prompts 失败: %s", e)
        return None


def _notify_conversation_turn() -> None:
    """通知使用量触发器对话轮次已完成（非阻塞，Phase 7D）"""
    try:
        from app.evaluation.rules.usage_trigger import get_usage_trigger
        trigger = get_usage_trigger()
        if trigger:
            trigger.on_conversation_turn()
    except Exception as e:
        logger.debug("[对话] 使用量触发器通知失败（非关键）: %s", e)


def _is_elevation_request(result: str) -> bool:
    """检测工具返回结果是否为权限提升请求

    工具返回的 JSON 中包含 __elevation_required__ 标记时为提升请求。
    """
    if not result or ELEVATION_MARKER not in result:
        return False
    try:
        import json
        data = json.loads(result)
        return isinstance(data, dict) and data.get(ELEVATION_MARKER) is True
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False


def _restore_chunk(content: str, redaction_map: dict[str, RedactionEntry]) -> str:
    """对单个流式 chunk 执行占位符替换。

    逐个检查 redaction_map 中的占位符是否出现在 chunk 中。
    占位符格式固定为 __REDACTED_xxxxxxxxxxxx__（26字符），
    大部分情况下 LLM 会将其作为完整 token 输出。
    """
    for placeholder, entry in redaction_map.items():
        if placeholder in content:
            content = content.replace(placeholder, entry.original)
    return content


def get_available_models(config: dict) -> list[dict]:
    """获取所有可用模型列表（API + CLI）"""
    router = get_router()
    return router.get_available_models(config)
