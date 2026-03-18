"""记忆注入器测试

覆盖：_validate_workspace_id / _safe_where / InjectedMemory 数据类
     _format_memory_text（双 section 分离）/ inject（并行调度 + L2 WHERE 子句）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pipeline.memory_injector import (
    MemoryInjector,
    InjectedMemory,
    InjectionResult,
    _validate_workspace_id,
    _safe_where,
)


# ─── _validate_workspace_id ───────────────────────────────────────────────

class TestValidateWorkspaceId:

    def test_纯字母数字被接受(self):
        assert _validate_workspace_id("workspace123") == "workspace123"

    def test_下划线和连字符被接受(self):
        assert _validate_workspace_id("my_workspace-1") == "my_workspace-1"

    def test_大写字母被接受(self):
        assert _validate_workspace_id("MyWorkspace") == "MyWorkspace"

    def test_global_被接受(self):
        assert _validate_workspace_id("global") == "global"

    def test_恰好64字符被接受(self):
        wid = "a" * 64
        assert _validate_workspace_id(wid) == wid

    def test_65字符回退到global(self):
        assert _validate_workspace_id("a" * 65) == "global"

    def test_空字符串回退到global(self):
        assert _validate_workspace_id("") == "global"

    @pytest.mark.parametrize("bad", [
        "ws<id>", "ws id", "ws.id", "ws@id", "ws#id", "ws/id", "ws=id",
    ])
    def test_特殊字符回退到global(self, bad):
        assert _validate_workspace_id(bad) == "global"

    def test_纯数字被接受(self):
        assert _validate_workspace_id("12345") == "12345"


# ─── _safe_where ──────────────────────────────────────────────────────────

class TestSafeWhere:

    def test_单条件直接返回(self):
        assert _safe_where(["type = 'fact'"]) == "type = 'fact'"

    def test_多条件用AND连接(self):
        result = _safe_where(["type = 'fact'", "priority = 'high'", "workspace_id = 'ws1'"])
        assert result == "type = 'fact' AND priority = 'high' AND workspace_id = 'ws1'"

    def test_空列表返回空字符串(self):
        assert _safe_where([]) == ""


# ─── InjectedMemory 数据类 ────────────────────────────────────────────────

class TestInjectedMemory:

    def test_默认source为user(self):
        m = InjectedMemory(content="test", type="fact", priority="high", layer="L1")
        assert m.source == "user"

    def test_common_sense_source可设置(self):
        m = InjectedMemory(content="test", type="fact", priority="high", layer="L2",
                           source="common_sense")
        assert m.source == "common_sense"

    def test_默认score为零(self):
        m = InjectedMemory(content="test", type="fact", priority="high", layer="L1")
        assert m.score == 0.0

    def test_所有字段可设置(self):
        m = InjectedMemory(content="hi", type="fact", priority="high",
                           layer="L2", score=0.85, source="user")
        assert m.content == "hi"
        assert m.score == 0.85
        assert m.layer == "L2"


# ─── InjectionResult 数据类 ───────────────────────────────────────────────

class TestInjectionResult:

    def test_默认值均为空(self):
        r = InjectionResult()
        assert r.memories == []
        assert r.memory_text == ""
        assert r.l1_count == 0
        assert r.l2_count == 0
        assert r.l3_count == 0


# ─── _format_memory_text ──────────────────────────────────────────────────

class TestFormatMemoryText:

    @staticmethod
    def _l1(content="核心事实"):
        return InjectedMemory(content=content, type="fact", priority="high", layer="L1")

    @staticmethod
    def _l2_user(content="个人记忆"):
        return InjectedMemory(content=content, type="episode", priority="medium",
                              layer="L2", source="user")

    @staticmethod
    def _l2_cs(content="常识条目"):
        return InjectedMemory(content=content, type="fact", priority="high",
                              layer="L2", source="common_sense")

    @staticmethod
    def _l3(content="行为规则"):
        return InjectedMemory(content=content, type="behavior", priority="medium", layer="L3")

    # ── section headers ──

    def test_L1内容在核心事实section下(self):
        text = MemoryInjector._format_memory_text([self._l1("用户名是张三")])
        assert "【核心事实】" in text
        assert "用户名是张三" in text

    def test_个人L2在相关记忆section下(self):
        text = MemoryInjector._format_memory_text([self._l2_user("喜欢咖啡")])
        assert "【相关记忆】" in text
        assert "喜欢咖啡" in text

    def test_常识L2在通用常识section下(self):
        text = MemoryInjector._format_memory_text([self._l2_cs("洗车需要开车")])
        assert "【通用常识——直接用于推理，无需说明来源】" in text
        assert "洗车需要开车" in text

    def test_L3内容在行为规则section下(self):
        text = MemoryInjector._format_memory_text([self._l3("偏好简洁")])
        assert "【行为规则】" in text
        assert "偏好简洁" in text

    # ── 双 section 分离（核心逻辑）──

    def test_常识和个人记忆使用不同section(self):
        memories = [self._l2_user("个人爱好"), self._l2_cs("洗车需要开车")]
        text = MemoryInjector._format_memory_text(memories)
        assert "【相关记忆】" in text
        assert "【通用常识——直接用于推理，无需说明来源】" in text

    def test_常识内容不出现在相关记忆section中(self):
        """确保 common_sense 条目严格在通用常识 section，不出现在【相关记忆】下"""
        memories = [self._l2_user("喜欢咖啡"), self._l2_cs("洗车需要开车去")]
        text = MemoryInjector._format_memory_text(memories)
        lines = text.split("\n")
        in_personal = False
        for line in lines:
            if "【相关记忆】" in line:
                in_personal = True
            if "【通用常识" in line:
                in_personal = False
            if in_personal and "洗车需要开车去" in line:
                pytest.fail("常识内容不应出现在【相关记忆】section 中")

    def test_无个人L2记忆时不出现相关记忆section(self):
        text = MemoryInjector._format_memory_text([self._l2_cs()])
        assert "【相关记忆】" not in text

    def test_无常识记忆时不出现通用常识section(self):
        text = MemoryInjector._format_memory_text([self._l2_user()])
        assert "【通用常识" not in text

    def test_四个section全部存在(self):
        memories = [self._l1(), self._l2_user(), self._l2_cs(), self._l3()]
        text = MemoryInjector._format_memory_text(memories)
        assert "【核心事实】" in text
        assert "【相关记忆】" in text
        assert "【通用常识" in text
        assert "【行为规则】" in text

    def test_输出以用户记忆分割线开头(self):
        text = MemoryInjector._format_memory_text([self._l1()])
        assert text.startswith("\n--- 用户记忆 ---")

    def test_空记忆列表只包含分割线(self):
        text = MemoryInjector._format_memory_text([])
        assert "--- 用户记忆 ---" in text
        assert "【" not in text


# ─── MemoryInjector.inject — 并行调度 ────────────────────────────────────

class TestMemoryInjectorInject:

    @pytest.mark.asyncio
    async def test_空query跳过L2检索(self):
        injector = MemoryInjector()
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])) as m2, \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="  ", workspace_id="ws1")
        m2.assert_not_called()
        assert result.l2_count == 0

    @pytest.mark.asyncio
    async def test_非空query调用L2检索(self):
        injector = MemoryInjector()
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])) as m2, \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            await injector.inject(query="今天天气如何", workspace_id="ws1")
        m2.assert_called_once_with("今天天气如何", "default", "ws1")

    @pytest.mark.asyncio
    async def test_L1结果正确写入memories(self):
        injector = MemoryInjector()
        l1_data = [{"content": "用户名是张三", "type": "fact", "priority": "high"}]
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=l1_data)), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="test", workspace_id="global")
        assert result.l1_count == 1
        assert result.memories[0].layer == "L1"
        assert result.memories[0].content == "用户名是张三"

    @pytest.mark.asyncio
    async def test_L2常识source字段保留(self):
        injector = MemoryInjector()
        l2_data = [{"content": "洗车需要开车", "source": "common_sense", "_distance": 0.1}]
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=l2_data)), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="洗车", workspace_id="ws1")
        assert result.l2_count == 1
        l2_mems = [m for m in result.memories if m.layer == "L2"]
        assert l2_mems[0].source == "common_sense"

    @pytest.mark.asyncio
    async def test_L3规则content来自rule字段(self):
        injector = MemoryInjector()
        l3_data = [{"rule": "用户偏好简洁", "type": "behavior", "confidence": 0.8}]
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=l3_data)):
            result = await injector.inject(query="test", workspace_id="global")
        assert result.l3_count == 1
        l3_mems = [m for m in result.memories if m.layer == "L3"]
        assert l3_mems[0].content == "用户偏好简洁"
        assert l3_mems[0].score == 0.8

    @pytest.mark.asyncio
    async def test_L1检索异常时l1_count为零不抛出(self):
        """asyncio.gather return_exceptions=True — L1 异常降级为空"""
        injector = MemoryInjector()
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(side_effect=RuntimeError("DB error"))), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="test", workspace_id="global")
        assert result.l1_count == 0

    @pytest.mark.asyncio
    async def test_无记忆时memory_text为空字符串(self):
        injector = MemoryInjector()
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="test", workspace_id="global")
        assert result.memory_text == ""

    @pytest.mark.asyncio
    async def test_有记忆时memory_text非空(self):
        injector = MemoryInjector()
        l1_data = [{"content": "测试内容", "type": "fact", "priority": "high"}]
        with patch.object(injector, "_fetch_l1_facts", AsyncMock(return_value=l1_data)), \
             patch.object(injector, "_fetch_l2_relevant", AsyncMock(return_value=[])), \
             patch.object(injector, "_fetch_l3_rules", AsyncMock(return_value=[])):
            result = await injector.inject(query="test", workspace_id="global")
        assert result.memory_text != ""
        assert "测试内容" in result.memory_text


# ─── _fetch_l2_relevant — WHERE 子句内容验证 ──────────────────────────────

class TestFetchL2WhereClause:
    """验证 L2 WHERE 子句同时包含 workspace_id 过滤和全局常识过滤"""

    @pytest.mark.asyncio
    async def test_where_clause包含workspace和common_sense(self):
        injector = MemoryInjector()
        captured = []

        class FakeSearch:
            def __init__(self):
                pass
            def where(self, clause, **kwargs):
                captured.append(clause)
                return self
            def limit(self, n):
                return self
            def to_list(self):
                return []

        mock_table = MagicMock()
        mock_table.search.return_value = FakeSearch()

        mock_embed = MagicMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 8)

        with patch("app.infrastructure.vector_db.get_table", return_value=mock_table), \
             patch("app.infrastructure.embedding.get_embedding_service", return_value=mock_embed):
            await injector._fetch_l2_relevant("洗车", "user1", "my_workspace")

        assert len(captured) == 1
        clause = captured[0]
        assert "my_workspace" in clause
        assert "common_sense" in clause
        assert "OR" in clause

    @pytest.mark.asyncio
    async def test_fetch_l2_DB异常时返回空列表(self):
        injector = MemoryInjector()
        with patch("app.infrastructure.vector_db.get_table", side_effect=RuntimeError("no DB")):
            result = await injector._fetch_l2_relevant("query", "user1", "global")
        assert result == []


# ─── set_reranker ─────────────────────────────────────────────────────────

class TestSetReranker:

    def test_set_reranker存储函数引用(self):
        injector = MemoryInjector()
        fn = lambda q, r: r
        injector.set_reranker(fn)
        assert injector._reranker is fn

    def test_默认reranker为None(self):
        assert MemoryInjector()._reranker is None
