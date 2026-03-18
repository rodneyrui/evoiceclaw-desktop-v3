"""eVoiceClaw Desktop v3 — AI OS 后端入口"""

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import load_config, validate_config

# ─── 日志配置 ────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_LOG_DATE_FORMAT = "%H:%M:%S"

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format=_LOG_FORMAT,
    datefmt=_LOG_DATE_FORMAT,
)

_app_logger = logging.getLogger("evoiceclaw")
_app_logger.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))

# 第三方库静音
if _LOG_LEVEL == "DEBUG":
    for noisy in ("httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("evoiceclaw.main")

API_PREFIX = "/api/v1"

# 前端构建产物目录
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend_dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理。"""

    # ── 配置验证 ──
    config_warnings = validate_config()
    for w in config_warnings:
        logger.warning("[配置检查] %s", w)

    # ── 加载配置 ──
    app.state.config = load_config()
    logger.info("配置加载完成 | LOG_LEVEL=%s", _LOG_LEVEL)

    # ── 初始化日志 SSE 推送 ──
    from app.api.v1.logs import install_log_handler
    install_log_handler()
    logger.info("日志 SSE 推送已启用")

    # ── 初始化数据库 ──
    from app.infrastructure.db import init_tables, init_audit_tables, close_all
    init_tables()
    init_audit_tables()
    logger.info("SQLite 数据库初始化完成")

    # ── 初始化向量数据库 ──
    from app.infrastructure.vector_db import init_tables as init_vector_tables, close as close_vector_db
    embedding_dim = app.state.config.get("embedding", {}).get("dim", 1536)
    init_vector_tables(dim=embedding_dim)
    logger.info("LanceDB 向量数据库初始化完成 (dim=%d)", embedding_dim)

    # ── Phase 7A: 加载预置评测数据（仅首次启动） ──
    from app.evaluation.preset_loader import check_and_load as load_preset_evaluations
    await load_preset_evaluations()
    logger.info("Phase 7A: 预置评测数据检查完成")

    # ── 初始化 Embedding 服务（Phase 2） ──
    from app.infrastructure.embedding import init_embedding_service
    from app.core.config import load_secrets
    secrets = load_secrets()
    embed_svc = init_embedding_service(app.state.config, secrets)
    logger.info("Embedding 服务初始化完成")

    # 本地模型预加载（避免首次请求冷启动延迟）
    if app.state.config.get("embedding", {}).get("provider") == "local":
        try:
            embed_svc._get_local_model()
            logger.info("本地 Embedding 模型预加载完成")
        except RuntimeError as e:
            logger.warning(
                "[Embedding] 本地模型预加载失败，记忆/实体功能暂不可用: %s"
                "  → 修复方式：pip install sentence-transformers", e,
            )

    # ── 初始化 kNN 需求向量预测器（语义路由加速） ──
    try:
        from app.kernel.router.knn_predictor import init_knn_predictor
        knn_pred = await init_knn_predictor()
        if knn_pred.is_available():
            logger.info("kNN predictor warmup 完成，%d 条锚点就绪",
                        len(knn_pred._anchor_texts))
        else:
            logger.warning("kNN predictor 预热未就绪，将降级使用 LLM 分类器")
    except Exception as e:
        logger.warning("kNN predictor 预热失败，将降级使用 LLM 分类器: %s", e)

    # ── 初始化隐私管道（Phase 2） ──
    from app.pipeline.pipeline import init_pipeline
    pipeline = init_pipeline(app.state.config)
    logger.info("隐私管道初始化完成")

    # 预热向量匹配（需要 Embedding 服务已初始化）
    try:
        await pipeline.warmup()
    except Exception as e:
        logger.debug("隐私管道预热跳过: %s", e)

    # ── 打印已启用的 Provider ──
    providers = app.state.config.get("providers", {})
    enabled_providers = [pid for pid, pcfg in providers.items() if pcfg.get("enabled") and pcfg.get("api_key")]
    logger.info("已启用 Provider: %s", enabled_providers or "(无，使用默认 llm 配置)")

    # ── 模型矩阵加载 + 配置一致性验证 ──
    from app.evaluation.matrix.model_matrix import get_matrix
    matrix = get_matrix()
    matrix.validate_against_config(app.state.config)

    # ── 初始化 LLM 内核（Phase 1） ──
    from app.kernel.providers.health import init_health_tracker
    health_tracker = init_health_tracker()
    health_tracker.load_config(app.state.config)
    logger.info("Provider 健康追踪器初始化完成")

    from app.kernel.tools.registry import init_tool_registry
    init_tool_registry()

    from app.kernel.router.policy_engine import init_policy_engine
    init_policy_engine(app.state.config)

    from app.kernel.router.llm_router import init_router
    init_router()

    # ── 预热 litellm（api_provider 模块级 import 已触发加载，此处确认并记录） ──
    import litellm as _litellm
    _litellm.drop_params = True   # 兼容不支持 stream_options 等参数的模型
    logger.info("litellm 预加载完成，首次请求无冷启动延迟")

    from app.services.chat_service import register_builtin_tools
    register_builtin_tools()
    logger.info("LLM 内核初始化完成")

    # ── Phase 3：审计服务 + Skills 目录初始化 ──
    from app.security.audit import init_audit
    init_audit()

    from app.services.skill_service import SKILLS_DIR
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Phase 3 初始化完成: 审计服务 + Skills 目录 (%s)", SKILLS_DIR)

    # ── 初始化浏览器服务 ──
    from app.services.browser_service import init_browser_service
    init_browser_service(app.state.config)

    # ── 初始化工作区服务 ──
    from app.services.workspace_service import init_workspace_service
    init_workspace_service()
    logger.info("WorkspaceService 初始化完成")

    # ── Phase 7C: 初始化评测调度器 ──
    from app.evaluation.scheduler import init_scheduler
    scheduler = init_scheduler(app.state.config)
    # 注意：调度器默认不自动启动，避免在开发环境中自动跑评测
    # 如需启动，取消下面的注释：
    # scheduler.start()
    logger.info("Phase 7C: 评测调度器初始化完成（未启动）")

    # ── Phase 7D: 规则生成器 + 热加载 + 使用量触发器 ──

    from app.evaluation.rules.rule_generator import init_rule_generator, RULES_DIR as _RULES_DIR, RULE_FILES as _RULE_FILES
    rule_generator = init_rule_generator(app.state.config)
    if rule_generator.is_available():
        logger.info("Phase 7D: 规则生成器初始化完成（规则生成模型已就绪）")
    else:
        logger.warning(
            "Phase 7D: 未检测到支持深度推理的模型，智能路由优化功能已禁用。"
            " 推荐配置以下任一 provider 并启用对应推理模型："
            " DeepSeek R1 (deepseek) / Kimi K2 Thinking (kimi) / 混元T1 (hunyuan) / o3-mini (openai)。"
            " 详见 config.example.cn.yaml 或 config.example.us.yaml。"
        )

    from app.evaluation.rules.hot_reload import init_hot_reloader
    hot_reloader = init_hot_reloader()
    hot_reloader.start()

    from app.evaluation.rules.usage_trigger import init_usage_trigger
    init_usage_trigger(app.state.config)
    logger.info("Phase 7D: 使用量触发器初始化完成")

    # ── Phase 7D: 启动时清理废弃规则文件（如 V3.2 移除的 routing_rules.yaml） ──
    if _RULES_DIR.exists():
        _current_rule_files = set(_RULE_FILES)
        for _f in _RULES_DIR.iterdir():
            if _f.is_file() and _f.suffix == ".yaml" and _f.name not in _current_rule_files:
                try:
                    _f.unlink()
                    logger.info("Phase 7D: 已清理废弃规则文件: %s", _f.name)
                except Exception as _e:
                    logger.warning("Phase 7D: 清理废弃文件失败 %s: %s", _f.name, _e)

    # ── Phase 7D: 预置默认规则回退（首次安装时从 preset/default_rules 复制） ──
    _model_prompts_path = _RULES_DIR / "model_prompts.yaml"
    if not _model_prompts_path.exists():
        _preset_rules_dir = Path(__file__).resolve().parent.parent / "data" / "preset" / "default_rules"
        if _preset_rules_dir.exists() and (_preset_rules_dir / "model_prompts.yaml").exists():
            import shutil as _shutil
            _RULES_DIR.mkdir(parents=True, exist_ok=True)
            _copied = 0
            for _src in _preset_rules_dir.iterdir():
                if _src.is_file() and _src.suffix == ".yaml":
                    _shutil.copy2(_src, _RULES_DIR / _src.name)
                    _copied += 1
            logger.info("Phase 7D: 首次安装，已从预置目录复制 %d 个默认规则文件", _copied)

    # ── Phase 7D: 首次启动自动生成规则（model_prompts.yaml 不存在时） ──
    if not _model_prompts_path.exists() and rule_generator.is_available():
        async def _auto_generate_on_startup() -> None:
            logger.info("Phase 7D: 首次启动，自动生成路由规则和人格配置...")
            success = await rule_generator.generate_rules()
            if success:
                logger.info("Phase 7D: 首次启动规则生成完成，热加载器将自动重载")
            else:
                logger.warning("Phase 7D: 首次启动规则生成失败，继续使用硬编码默认规则")
        import asyncio as _asyncio
        _asyncio.create_task(_auto_generate_on_startup())
        logger.info("Phase 7D: 已调度首次启动规则生成任务（后台执行）")
    elif not rule_generator.is_available():
        logger.warning("Phase 7D: 无规则生成模型可用，跳过自动规则生成")

    yield

    # ── 优雅关闭 ──
    # 停止热加载器
    try:
        from app.evaluation.rules.hot_reload import get_hot_reloader
        reloader = get_hot_reloader()
        if reloader:
            await reloader.stop()
    except Exception as e:
        logger.warning(f"停止热加载器失败: {e}")

    # 停止调度器
    try:
        from app.evaluation.scheduler import get_scheduler
        scheduler = get_scheduler()
        await scheduler.stop()
        logger.info("评测调度器已停止")
    except Exception as e:
        logger.warning(f"停止调度器失败: {e}")

    close_vector_db()
    close_all()
    logger.info("所有数据库连接已关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="eVoiceClaw Desktop v3 — AI OS",
        version="3.0.0",
        lifespan=lifespan,
    )

    # CORS 配置
    _default_origins = [
        "http://localhost:5173",
        "http://localhost:28771",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:28771",
    ]
    try:
        _cfg = load_config()
        origins = _cfg.get("cors", {}).get("allow_origins", _default_origins)
    except Exception as e:
        logger.debug("[Main] 加载 CORS 配置失败，使用默认值: %s", e)
        origins = _default_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 速率限制中间件（SA-7）
    from app.security.rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    # ── 注册 API 路由 ──
    from app.api.v1.system import router as system_router
    app.include_router(system_router, prefix=API_PREFIX)

    from app.api.v1.chat import router as chat_router
    app.include_router(chat_router, prefix=API_PREFIX + "/chat", tags=["chat"])

    # Phase 2+ 会逐步注册以下路由:
    # from app.api.v1 import memory, workspace, auth
    # app.include_router(memory.router, prefix=API_PREFIX, tags=["memory"])
    # app.include_router(workspace.router, prefix=API_PREFIX, tags=["workspace"])
    # app.include_router(auth.router, prefix=API_PREFIX, tags=["auth"])

    from app.api.v1.config import router as config_router
    app.include_router(config_router, prefix=API_PREFIX + "/config", tags=["config"])

    from app.api.v1.skills import router as skills_router
    app.include_router(skills_router, prefix=API_PREFIX + "/skills", tags=["skills"])

    from app.api.v1.audit import router as audit_router
    app.include_router(audit_router, prefix=API_PREFIX + "/audit", tags=["audit"])

    from app.api.v1.workspace import router as workspace_router
    app.include_router(workspace_router, prefix=API_PREFIX + "/workspaces", tags=["workspace"])

    from app.api.v1.evaluation import router as evaluation_router
    app.include_router(evaluation_router, prefix=API_PREFIX + "/evaluation", tags=["evaluation"])

    from app.api.v1.sessions import router as sessions_router
    app.include_router(sessions_router, prefix=API_PREFIX + "/sessions", tags=["sessions"])

    from app.api.v1.permissions import router as permissions_router
    app.include_router(permissions_router, prefix=API_PREFIX + "/permissions", tags=["permissions"])

    from app.api.v1.logs import router as logs_router
    app.include_router(logs_router, prefix=API_PREFIX, tags=["logs"])

    # ── 前端静态资源 + SPA 路由回退 ──
    index_html = FRONTEND_DIST / "index.html"
    if FRONTEND_DIST.is_dir() and index_html.is_file():
        _frontend_root = FRONTEND_DIST.resolve()

        @app.get("/{full_path:path}")
        def _serve_frontend(full_path: str):
            if full_path:
                file_path = (FRONTEND_DIST / full_path).resolve()
                # 安全检查: 确保解析后的路径在 frontend_dist 目录内（防路径遍历）
                try:
                    file_path.relative_to(_frontend_root)
                except ValueError:
                    return FileResponse(index_html, media_type="text/html")
                if file_path.is_file():
                    return FileResponse(file_path)
            return FileResponse(index_html, media_type="text/html")
    else:
        logger.info("frontend_dist 未找到，仅提供 API 服务")

    return app


app = create_app()
