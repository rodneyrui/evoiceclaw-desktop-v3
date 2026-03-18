"""LanceDB 连接管理器：嵌入式向量数据库

管理 4 张核心向量表:
- entities: 实体类别映射
- memories: 用户记忆
- distilled: 蒸馏规则
- model_evaluations: 模型评测结果（Phase 7）

预留 user_id 参数，当前默认 "default"（R3 多用户隔离）。
"""

import logging
import os
from pathlib import Path

import lancedb
import pyarrow as pa

logger = logging.getLogger("evoiceclaw.vector_db")

# LanceDB 数据目录
# 优先使用环境变量 EVOICECLAW_VECTORS_DIR（适配不支持原子 rename 的文件系统，如 exFAT）
# 默认使用 ~/.evoiceclaw-v3/vectors/（本地 APFS 文件系统，确保原子操作支持）
_DEFAULT_VECTORS_DIR = Path.home() / ".evoiceclaw-v3" / "vectors"
_DATA_DIR = Path(os.environ.get("EVOICECLAW_VECTORS_DIR", str(_DEFAULT_VECTORS_DIR)))

# 向量维度（根据 embedding 模型配置）
# text-embedding-3-small: 1536 维
# BAAI/bge-small-zh-v1.5: 512 维
DEFAULT_VECTOR_DIM = 1536

_db_instance: lancedb.DBConnection | None = None

# ── 表实例缓存：避免每次 get_table() 都调用 open_table() ──
_table_cache: dict[str, lancedb.table.Table] = {}


def get_db(user_id: str = "default") -> lancedb.DBConnection:
    """获取 LanceDB 连接（单例，嵌入式模式）。

    Args:
        user_id: 预留多用户隔离（R3），当前未使用
    """
    global _db_instance
    if _db_instance is not None:
        return _db_instance

    db_path = _DATA_DIR
    db_path.mkdir(parents=True, exist_ok=True)

    _db_instance = lancedb.connect(str(db_path))
    logger.info("[VectorDB] LanceDB 连接已建立: %s", db_path)
    return _db_instance


def _entities_schema(dim: int = DEFAULT_VECTOR_DIM) -> pa.Schema:
    """实体类别映射表 Schema。"""
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("type", pa.string()),           # PERSON/ORG/LOCATION/PRODUCT/...
        pa.field("category", pa.string()),        # 细分类别
        pa.field("vector", pa.list_(pa.float32(), dim)),
        pa.field("metadata", pa.string()),        # JSON 字符串
        pa.field("last_seen", pa.string()),       # ISO 8601 时间戳
        pa.field("frequency", pa.int32()),        # 出现次数
        pa.field("workspace_id", pa.string()),    # 工作区隔离（宪法第3/6条）
    ])


def _memories_schema(dim: int = DEFAULT_VECTOR_DIM) -> pa.Schema:
    """用户记忆表 Schema。"""
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("content", pa.string()),
        pa.field("type", pa.string()),            # fact/preference/summary/episode
        pa.field("priority", pa.string()),        # high/medium/low
        pa.field("vector", pa.list_(pa.float32(), dim)),
        pa.field("source_conv_id", pa.string()),  # 来源会话 ID
        pa.field("entities", pa.string()),        # JSON: 关联实体 ID 列表
        pa.field("created_at", pa.string()),
        pa.field("last_recalled", pa.string()),
        pa.field("recall_count", pa.int32()),
        pa.field("ttl_days", pa.int32()),         # 可选过期天数（0 = 永久保留）
        pa.field("user_id", pa.string()),         # R3 预留
        pa.field("workspace_id", pa.string()),    # 工作区隔离（宪法第3/6条）
        pa.field("source", pa.string()),          # 记忆来源：user / common_sense
    ])


def _distilled_schema(dim: int = DEFAULT_VECTOR_DIM) -> pa.Schema:
    """蒸馏规则表 Schema。"""
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("rule", pa.string()),            # 蒸馏出的行为规则（自然语言）
        pa.field("type", pa.string()),            # behavior/preference/constraint
        pa.field("vector", pa.list_(pa.float32(), dim)),
        pa.field("confidence", pa.float32()),     # 0-1 置信度
        pa.field("evidence_count", pa.int32()),   # 支持该规则的交互次数
        pa.field("created_at", pa.string()),
        pa.field("updated_at", pa.string()),
        pa.field("user_id", pa.string()),         # R3 预留
        pa.field("workspace_id", pa.string()),    # 工作区隔离（宪法第3/6条）
    ])


def _model_evaluations_schema() -> pa.Schema:
    """模型评测结果表 Schema（Phase 7）。"""
    return pa.schema([
        pa.field("eval_id", pa.string()),
        pa.field("model_id", pa.string()),
        pa.field("timestamp", pa.timestamp("ms")),
        pa.field("source", pa.string()),          # benchmark_real / preset_v2 / evaluated
        pa.field("dimension_scores", pa.string()),  # JSON: {coding: 100, ...}
        pa.field("avg_latency_ms", pa.int32()),
        pa.field("avg_input_tokens", pa.int32()),
        pa.field("avg_output_tokens", pa.int32()),
        pa.field("cost_input_per_m", pa.float32()),
        pa.field("cost_output_per_m", pa.float32()),
        pa.field("context_window", pa.int32()),
        pa.field("benchmark_version", pa.string()),
        pa.field("eval_version", pa.string()),
        pa.field("not_measured_dims", pa.string()),  # JSON: ["knowledge_medical"]
    ])


def _migrate_table_columns(table, table_name: str, required_cols: list[tuple[str, str]]) -> None:
    """检测并自动补齐缺失的列（LanceDB add_columns，不破坏现有数据）。

    Args:
        table: LanceDB Table 实例
        table_name: 表名（用于日志）
        required_cols: [(列名, SQL默认值表达式), ...]
    """
    try:
        existing = {field.name for field in table.schema}
        missing = [(col, expr) for col, expr in required_cols if col not in existing]
        if not missing:
            return
        additions = {col: expr for col, expr in missing}
        table.add_columns(additions)
        for col, _ in missing:
            logger.info("[VectorDB] 已自动添加列 %s.%s", table_name, col)
    except Exception as e:
        missing_names = [col for col, _ in required_cols
                         if col not in {f.name for f in table.schema}]
        if missing_names:
            logger.warning(
                "[VectorDB] 无法自动迁移 %s 表缺失列 %s: %s — 请删除表目录后重启",
                table_name, missing_names, e,
            )


def init_tables(dim: int = DEFAULT_VECTOR_DIM) -> None:
    """初始化所有向量表（幂等操作，已存在则跳过）。

    Args:
        dim: 向量维度，由 embedding 模型决定
    """
    db = get_db()
    existing = set(db.table_names())

    if "entities" not in existing:
        db.create_table("entities", schema=_entities_schema(dim))
        logger.info("[VectorDB] 创建表: entities (dim=%d)", dim)
    else:
        logger.info("[VectorDB] 表已存在: entities")
        _migrate_table_columns(
            db.open_table("entities"), "entities",
            [("workspace_id", "CAST('global' AS string)")]
        )

    if "memories" not in existing:
        db.create_table("memories", schema=_memories_schema(dim))
        logger.info("[VectorDB] 创建表: memories (dim=%d)", dim)
    else:
        logger.info("[VectorDB] 表已存在: memories")
        _migrate_table_columns(
            db.open_table("memories"), "memories",
            [
                ("workspace_id", "CAST('global' AS string)"),
                ("source", "CAST('user' AS string)"),
            ]
        )

    if "distilled" not in existing:
        db.create_table("distilled", schema=_distilled_schema(dim))
        logger.info("[VectorDB] 创建表: distilled (dim=%d)", dim)
    else:
        logger.info("[VectorDB] 表已存在: distilled")
        _migrate_table_columns(
            db.open_table("distilled"), "distilled",
            [("workspace_id", "CAST('global' AS string)")]
        )

    if "model_evaluations" not in existing:
        db.create_table("model_evaluations", schema=_model_evaluations_schema())
        logger.info("[VectorDB] 创建表: model_evaluations (Phase 7)")
    else:
        logger.info("[VectorDB] 表已存在: model_evaluations")

    logger.info("[VectorDB] 向量表初始化完成（共 %d 张表）", len(db.table_names()))


def get_table(name: str) -> lancedb.table.Table:
    """获取指定向量表（带缓存，避免重复 open_table()）。

    Args:
        name: 表名 (entities / memories / distilled / model_evaluations)

    Raises:
        ValueError: 表不存在
    """
    # 查缓存
    if name in _table_cache:
        return _table_cache[name]

    db = get_db()
    if name not in db.table_names():
        raise ValueError(f"向量表 '{name}' 不存在，请先调用 init_tables()")

    table = db.open_table(name)
    _table_cache[name] = table
    logger.debug("[VectorDB] 表已缓存: %s", name)
    return table


def close() -> None:
    """关闭 LanceDB 连接并清空表缓存。"""
    global _db_instance
    _table_cache.clear()
    _db_instance = None
    logger.info("[VectorDB] LanceDB 连接已关闭（表缓存已清空）")
