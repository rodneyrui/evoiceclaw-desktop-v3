"""预置数据加载器测试

覆盖：load_preset_data（跳过条件 + 写入记录字段校验）
     load_common_sense_data（幂等保护 + source/workspace_id/ttl_days 字段）
     check_and_load（两个独立 try/except）
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from app.evaluation.preset_loader import (
    load_preset_data,
    load_common_sense_data,
    check_and_load,
)


# ─── load_preset_data ──────────────────────────────────────────────────────

class TestLoadPresetData:

    @pytest.mark.asyncio
    async def test_表不存在时直接返回(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        with patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table") as mock_get_table:
            await load_preset_data()
        mock_get_table.assert_not_called()

    @pytest.mark.asyncio
    async def test_表非空时跳过加载(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["model_evaluations"]
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 5

        preset_data = {"version": "3.0", "models": []}
        preset_json = json.dumps(preset_data).encode()

        # 计算与代码一致的 version_tag
        import hashlib
        content_hash = hashlib.sha256(preset_json).hexdigest()[:16]
        version_tag = f"v3.0@{content_hash}"

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_bytes.return_value = preset_json

        with patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("app.evaluation.preset_loader.PRESET_DATA_PATH", mock_path), \
             patch("app.evaluation.preset_loader._get_db_preset_version", return_value=version_tag):
            await load_preset_data()
        mock_table.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_预置文件不存在时跳过加载(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["model_evaluations"]
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 0
        with patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("app.evaluation.preset_loader.PRESET_DATA_PATH") as mock_path:
            mock_path.exists.return_value = False
            await load_preset_data()
        mock_table.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_成功加载时调用table_add(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["model_evaluations"]
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 0

        preset_data = {
            "models": [
                {
                    "model_id": "deepseek/deepseek-chat",
                    "source": "official",
                    "dimension_scores": {"coding": 5},
                    "avg_latency_ms": 500,
                    "cost_input_per_m": 2.0,
                    "cost_output_per_m": 3.0,
                    "context_window": 128000,
                }
            ]
        }
        preset_json = json.dumps(preset_data).encode()
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_bytes.return_value = preset_json

        with patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("app.evaluation.preset_loader.PRESET_DATA_PATH", mock_path):
            await load_preset_data()

        mock_table.add.assert_called_once()
        records = mock_table.add.call_args[0][0]
        assert len(records) == 1
        assert records[0]["model_id"] == "deepseek/deepseek-chat"

    @pytest.mark.asyncio
    async def test_写入记录包含必要字段(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["model_evaluations"]
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 0

        preset_data = {
            "models": [
                {
                    "model_id": "test/model",
                    "source": "official",
                    "dimension_scores": {},
                }
            ]
        }
        preset_json = json.dumps(preset_data).encode()
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_bytes.return_value = preset_json

        with patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("app.evaluation.preset_loader.PRESET_DATA_PATH", mock_path):
            await load_preset_data()

        record = mock_table.add.call_args[0][0][0]
        for field in ("eval_id", "model_id", "timestamp", "source", "dimension_scores",
                      "avg_latency_ms", "benchmark_version", "eval_version"):
            assert field in record, f"缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_DB异常时不抛出(self):
        with patch("app.evaluation.preset_loader.get_db", side_effect=RuntimeError("DB error")):
            await load_preset_data()  # 不应抛出


# ─── load_common_sense_data ────────────────────────────────────────────────

class TestLoadCommonSenseData:

    @pytest.mark.asyncio
    async def test_常识文件不存在时不崩溃(self):
        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path:
            mock_path.exists.return_value = False
            await load_common_sense_data()

    @pytest.mark.asyncio
    async def test_memories表不存在时跳过(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path, \
             patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table") as mock_get_table:
            mock_path.exists.return_value = True
            await load_common_sense_data()
        mock_get_table.assert_not_called()

    @pytest.mark.asyncio
    async def test_已有常识记忆时幂等跳过(self):
        """source='common_sense' 已存在 → 不再写入"""
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["memories"]

        mock_search = MagicMock()
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = [{"id": "cs_001"}]  # 非空 → 已存在

        mock_table = MagicMock()
        mock_table.search.return_value = mock_search
        mock_table.count_rows.return_value = 10

        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path, \
             patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table):
            mock_path.exists.return_value = True
            await load_common_sense_data()

        mock_table.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_写入记录source为common_sense(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["memories"]

        mock_search = MagicMock()
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []  # 空 → 未加载

        mock_table = MagicMock()
        mock_table.search.return_value = mock_search

        cs_data = {"entries": [{"id": "cs_001", "content": "洗车需要开车去洗车店"}]}
        mock_embed = MagicMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 8)

        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path, \
             patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("builtins.open", mock_open(read_data=json.dumps(cs_data))), \
             patch("app.infrastructure.embedding.get_embedding_service",
                   return_value=mock_embed):
            mock_path.exists.return_value = True
            await load_common_sense_data()

        mock_table.add.assert_called_once()
        record = mock_table.add.call_args[0][0][0]
        assert record["source"] == "common_sense"

    @pytest.mark.asyncio
    async def test_写入记录workspace_id为global(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["memories"]

        mock_search = MagicMock()
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []

        mock_table = MagicMock()
        mock_table.search.return_value = mock_search

        cs_data = {"entries": [{"id": "cs_001", "content": "测试内容"}]}
        mock_embed = MagicMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 8)

        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path, \
             patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("builtins.open", mock_open(read_data=json.dumps(cs_data))), \
             patch("app.infrastructure.embedding.get_embedding_service",
                   return_value=mock_embed):
            mock_path.exists.return_value = True
            await load_common_sense_data()

        record = mock_table.add.call_args[0][0][0]
        assert record["workspace_id"] == "global"

    @pytest.mark.asyncio
    async def test_写入记录ttl_days为0表示永久保留(self):
        mock_db = MagicMock()
        mock_db.table_names.return_value = ["memories"]

        mock_search = MagicMock()
        mock_search.where.return_value = mock_search
        mock_search.limit.return_value = mock_search
        mock_search.to_list.return_value = []

        mock_table = MagicMock()
        mock_table.search.return_value = mock_search

        cs_data = {"entries": [{"id": "cs_002", "content": "另一条常识"}]}
        mock_embed = MagicMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 8)

        with patch("app.evaluation.preset_loader.COMMON_SENSE_PATH") as mock_path, \
             patch("app.evaluation.preset_loader.get_db", return_value=mock_db), \
             patch("app.evaluation.preset_loader.get_table", return_value=mock_table), \
             patch("builtins.open", mock_open(read_data=json.dumps(cs_data))), \
             patch("app.infrastructure.embedding.get_embedding_service",
                   return_value=mock_embed):
            mock_path.exists.return_value = True
            await load_common_sense_data()

        record = mock_table.add.call_args[0][0][0]
        assert record["ttl_days"] == 0


# ─── check_and_load ────────────────────────────────────────────────────────

class TestCheckAndLoad:

    @pytest.mark.asyncio
    async def test_两个加载函数都被调用(self):
        with patch("app.evaluation.preset_loader.load_preset_data", AsyncMock()) as m1, \
             patch("app.evaluation.preset_loader.load_common_sense_data", AsyncMock()) as m2:
            await check_and_load()
        m1.assert_called_once()
        m2.assert_called_once()

    @pytest.mark.asyncio
    async def test_preset异常不影响common_sense加载(self):
        """两个独立 try/except：preset 抛异常不阻止 common_sense 执行"""
        with patch("app.evaluation.preset_loader.load_preset_data",
                   AsyncMock(side_effect=RuntimeError("preset DB error"))), \
             patch("app.evaluation.preset_loader.load_common_sense_data", AsyncMock()) as m2:
            await check_and_load()
        m2.assert_called_once()

    @pytest.mark.asyncio
    async def test_common_sense异常不抛出(self):
        with patch("app.evaluation.preset_loader.load_preset_data", AsyncMock()), \
             patch("app.evaluation.preset_loader.load_common_sense_data",
                   AsyncMock(side_effect=RuntimeError("cs error"))):
            await check_and_load()  # 不应抛出
