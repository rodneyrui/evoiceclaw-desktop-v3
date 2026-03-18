"""预置评测数据加载器 — 启动时注入/更新 LanceDB

内容 hash 变更检测：对 preset_evaluations.json 的内容计算 SHA-256 摘要，
与 LanceDB 中已有数据的 benchmark_version 字段对比。
文件有任何改动即自动删除旧预置数据并重新加载。
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from app.infrastructure.vector_db import get_db, get_table

logger = logging.getLogger("evoiceclaw.evaluation.preset_loader")

PRESET_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "preset" / "preset_evaluations.json"
COMMON_SENSE_PATH = Path(__file__).parent.parent.parent / "data" / "preset" / "preset_common_sense.json"


async def load_preset_data() -> None:
    """加载预置评测数据到 LanceDB

    内容 hash 变更检测：
    - 表为空 → 直接加载
    - 表有数据且 hash 相同 → 跳过
    - 表有数据但 hash 不同 → 删除旧预置数据，重新加载
    """
    try:
        db = get_db()

        # 检查表是否存在
        if "model_evaluations" not in db.table_names():
            logger.warning("[PresetLoader] model_evaluations 表不存在，跳过预置数据加载")
            return

        table = get_table("model_evaluations")

        # 读取预置数据文件
        if not PRESET_DATA_PATH.exists():
            logger.warning(f"[PresetLoader] 预置数据文件不存在: {PRESET_DATA_PATH}")
            return

        raw_bytes = PRESET_DATA_PATH.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
        preset = json.loads(raw_bytes)

        json_version = preset.get("version", "1.0")
        models = preset["models"]
        # benchmark_version 格式: "v3.0@a1b2c3d4e5f6"（人类可读版本 + 内容 hash）
        version_tag = f"v{json_version}@{content_hash}"

        # 检查 LanceDB 中已有数据的版本标签
        count = table.count_rows()
        if count > 0:
            db_version_tag = _get_db_preset_version(table)
            if db_version_tag == version_tag:
                logger.info(
                    "[PresetLoader] 数据未变更 (%s)，%d 条，跳过加载",
                    version_tag, count,
                )
                return
            # hash 不同，文件有改动，删除旧数据后重新加载
            logger.info(
                "[PresetLoader] 数据变更检测: %s → %s，删除旧预置数据并重新加载",
                db_version_tag, version_tag,
            )
            _delete_preset_rows(table)

        # 转换为 LanceDB 格式
        logger.info(f"[PresetLoader] 开始加载 {len(models)} 个模型的预置数据 ({version_tag})")
        records = []
        now_ms = int(datetime.now().timestamp() * 1000)
        for model in models:
            record = {
                "eval_id": f"preset_{model['model_id'].replace('/', '_')}",
                "model_id": model["model_id"],
                "timestamp": now_ms,
                "source": model.get("source", "preset"),
                "dimension_scores": json.dumps(model["dimension_scores"], ensure_ascii=False),
                "avg_latency_ms": model.get("avg_latency_ms", 0),
                "avg_input_tokens": 0,
                "avg_output_tokens": 0,
                "cost_input_per_m": model.get("cost_input_per_m", 0.0),
                "cost_output_per_m": model.get("cost_output_per_m", 0.0),
                "context_window": model.get("context_window", 128000),
                "benchmark_version": version_tag,
                "eval_version": "1.0",
                "not_measured_dims": json.dumps(model.get("not_measured_dims", []), ensure_ascii=False),
            }
            records.append(record)

        # 批量写入
        table.add(records)
        logger.info(f"[PresetLoader] ✅ 预置数据加载完成，共 {len(records)} 条 ({version_tag})")

    except Exception as e:
        logger.error(f"[PresetLoader] 加载预置数据失败: {e}", exc_info=True)


def _get_db_preset_version(table) -> str:
    """从 LanceDB 中读取已有预置数据的 benchmark_version"""
    try:
        rows = (
            table.search()
            .where("eval_id LIKE 'preset_%'", prefilter=True)
            .limit(1)
            .to_list()
        )
        if rows:
            return rows[0].get("benchmark_version", "unknown")
    except Exception as e:
        logger.debug("[PresetLoader] 读取已有版本失败: %s", e)
    return "unknown"


def _delete_preset_rows(table) -> None:
    """删除 LanceDB 中所有 eval_id 以 'preset_' 开头的行"""
    try:
        table.delete("eval_id LIKE 'preset_%'")
        logger.info("[PresetLoader] 旧预置数据已删除")
    except Exception as e:
        logger.warning("[PresetLoader] 删除旧预置数据失败: %s", e)


async def check_and_load() -> None:
    """检查并加载预置数据（在 main.py lifespan 中调用）"""
    try:
        await load_preset_data()
    except Exception as e:
        logger.error(f"[PresetLoader] 加载预置数据失败: {e}", exc_info=True)

    try:
        await load_common_sense_data()
    except Exception as e:
        logger.error(f"[PresetLoader] 加载常识记忆失败: {e}", exc_info=True)


async def load_common_sense_data() -> None:
    """将通用常识条目写入 memories 表（永久保留，所有工作区可用）

    - source = 'common_sense'，workspace_id = 'global'
    - ttl_days = 0 表示永久保留，不参与过期清理
    - 幂等：通过条目 id 检查是否已存在，避免重复写入
    """
    if not COMMON_SENSE_PATH.exists():
        logger.warning("[CommonSense] 常识数据文件不存在: %s", COMMON_SENSE_PATH)
        return

    db = get_db()
    if "memories" not in db.table_names():
        logger.warning("[CommonSense] memories 表不存在，跳过常识记忆加载")
        return

    try:
        table = get_table("memories")
    except Exception as e:
        logger.warning("[CommonSense] 获取 memories 表失败: %s", e)
        return

    # 检查是否已有常识记忆（幂等保护）
    try:
        existing = (
            table.search()
            .where("source = 'common_sense'", prefilter=True)
            .limit(1)
            .to_list()
        )
        if existing:
            count = table.count_rows(filter="source = 'common_sense'")
            logger.info("[CommonSense] 常识记忆已存在 %d 条，跳过加载", count)
            return
    except Exception as e:
        logger.debug("[CommonSense] 检查已有条目时异常（可能是旧表缺少 source 列）: %s", e)
        logger.warning("[CommonSense] memories 表可能缺少 source 列，请删除后重建以启用常识记忆功能")
        return

    with open(COMMON_SENSE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    logger.info("[CommonSense] 开始加载 %d 条常识记忆（需向量化）", len(entries))

    # 向量化并写入
    try:
        from app.infrastructure.embedding import get_embedding_service
        embed_svc = get_embedding_service()
    except Exception as e:
        logger.error("[CommonSense] Embedding 服务不可用，跳过常识加载: %s", e)
        return

    now = datetime.now().isoformat()
    records = []
    for entry in entries:
        try:
            vector = await embed_svc.embed(entry["content"])
            records.append({
                "id": entry["id"],
                "content": entry["content"],
                "type": "fact",
                "priority": "high",
                "vector": vector,
                "source_conv_id": "common_sense_preset",
                "entities": "[]",
                "created_at": now,
                "last_recalled": now,
                "recall_count": 0,
                "ttl_days": 0,           # 0 = 永久保留
                "user_id": "system",
                "workspace_id": "global",
                "source": "common_sense",
            })
        except Exception as e:
            logger.warning("[CommonSense] 条目 %s 向量化失败，跳过: %s", entry["id"], e)

    if records:
        table.add(records)
        logger.info("[CommonSense] ✅ 常识记忆加载完成，共 %d 条", len(records))
