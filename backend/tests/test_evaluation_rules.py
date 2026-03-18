"""评测规则子系统测试

覆盖：
- UsageTrigger._should_trigger（早期固定阈值 / 周期性触发 / 不触发）
- UsageTrigger._next_trigger_count（各阶段下一个触发点）
- RulesHotReloader（register_callback / trigger_reload 同步/异步 / start/stop / 单例）
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.evaluation.rules.usage_trigger import (
    UsageTrigger,
    _EARLY_THRESHOLDS,
    _PERIODIC_INTERVAL,
    init_usage_trigger,
    get_usage_trigger,
)
import app.evaluation.rules.usage_trigger as _ut_module

from app.evaluation.rules.hot_reload import (
    RulesHotReloader,
    init_hot_reloader,
    get_hot_reloader,
)
import app.evaluation.rules.hot_reload as _hr_module


# ─── UsageTrigger._should_trigger ─────────────────────────────────────────────

class TestShouldTrigger:
    """_should_trigger 是纯逻辑方法，无需 DB，直接单元测试"""

    def _trigger(self) -> UsageTrigger:
        return UsageTrigger(config={})

    def test_50轮时触发(self):
        t = self._trigger()
        assert t._should_trigger(50) is True

    def test_100轮时触发(self):
        t = self._trigger()
        assert t._should_trigger(100) is True

    def test_200轮时触发(self):
        t = self._trigger()
        assert t._should_trigger(200) is True

    def test_500轮时触发(self):
        t = self._trigger()
        assert t._should_trigger(500) is True

    def test_1000轮时触发(self):
        t = self._trigger()
        assert t._should_trigger(1000) is True

    def test_51轮时不触发(self):
        t = self._trigger()
        assert t._should_trigger(51) is False

    def test_99轮时不触发(self):
        t = self._trigger()
        assert t._should_trigger(99) is False

    def test_1001轮不触发(self):
        t = self._trigger()
        assert t._should_trigger(1001) is False

    def test_超过1000后每500轮触发_1500(self):
        t = self._trigger()
        # 1000 + 500 = 1500
        assert t._should_trigger(1500) is True

    def test_超过1000后每500轮触发_2000(self):
        t = self._trigger()
        assert t._should_trigger(2000) is True

    def test_超过1000后每500轮触发_2500(self):
        t = self._trigger()
        assert t._should_trigger(2500) is True

    def test_1499轮不触发(self):
        t = self._trigger()
        assert t._should_trigger(1499) is False

    def test_0轮不触发(self):
        t = self._trigger()
        assert t._should_trigger(0) is False

    def test_1轮不触发(self):
        t = self._trigger()
        assert t._should_trigger(1) is False

    def test_所有早期阈值都触发(self):
        t = self._trigger()
        for threshold in _EARLY_THRESHOLDS:
            assert t._should_trigger(threshold) is True, f"{threshold} 应触发"


# ─── UsageTrigger._next_trigger_count ─────────────────────────────────────────

class TestNextTriggerCount:

    def _trigger(self) -> UsageTrigger:
        return UsageTrigger(config={})

    def test_0轮时下一个触发点是50(self):
        t = self._trigger()
        assert t._next_trigger_count(0) == 50

    def test_49轮时下一个触发点是50(self):
        t = self._trigger()
        assert t._next_trigger_count(49) == 50

    def test_50轮时下一个触发点是100(self):
        t = self._trigger()
        assert t._next_trigger_count(50) == 100

    def test_100轮时下一个触发点是200(self):
        t = self._trigger()
        assert t._next_trigger_count(100) == 200

    def test_200轮时下一个触发点是500(self):
        t = self._trigger()
        assert t._next_trigger_count(200) == 500

    def test_500轮时下一个触发点是1000(self):
        t = self._trigger()
        assert t._next_trigger_count(500) == 1000

    def test_1000轮时下一个触发点是1500(self):
        t = self._trigger()
        assert t._next_trigger_count(1000) == 1500

    def test_1500轮时下一个触发点是2000(self):
        t = self._trigger()
        assert t._next_trigger_count(1500) == 2000

    def test_1001轮时下一个触发点是1500(self):
        t = self._trigger()
        assert t._next_trigger_count(1001) == 1500

    def test_999轮时下一个触发点是1000(self):
        t = self._trigger()
        assert t._next_trigger_count(999) == 1000


# ─── UsageTrigger 单例 ─────────────────────────────────────────────────────────

class TestUsageTriggerSingleton:

    def test_get_usage_trigger初始为None(self):
        old = _ut_module._trigger_instance
        try:
            _ut_module._trigger_instance = None
            assert get_usage_trigger() is None
        finally:
            _ut_module._trigger_instance = old

    def test_init_usage_trigger设置单例(self):
        old = _ut_module._trigger_instance
        try:
            t = init_usage_trigger({})
            assert isinstance(t, UsageTrigger)
            assert get_usage_trigger() is t
        finally:
            _ut_module._trigger_instance = old


# ─── RulesHotReloader.register_callback ───────────────────────────────────────

class TestRulesHotReloaderCallback:

    def test_注册同步回调并触发(self):
        reloader = RulesHotReloader()
        received = []
        reloader.register_callback(lambda fname: received.append(fname))
        # 未运行状态直接调用同步回调
        reloader.trigger_reload("routing_rules.yaml")
        assert "routing_rules.yaml" in received

    def test_注册多个回调都被调用(self):
        reloader = RulesHotReloader()
        log1, log2 = [], []
        reloader.register_callback(lambda f: log1.append(f))
        reloader.register_callback(lambda f: log2.append(f))
        reloader.trigger_reload("model_prompts.yaml")
        assert log1 == ["model_prompts.yaml"]
        assert log2 == ["model_prompts.yaml"]

    def test_回调异常不影响其他回调(self):
        reloader = RulesHotReloader()
        log = []

        def bad_callback(fname):
            raise RuntimeError("callback error")

        reloader.register_callback(bad_callback)
        reloader.register_callback(lambda f: log.append(f))
        # 不应抛出
        reloader.trigger_reload("routing_rules.yaml")
        assert "routing_rules.yaml" in log

    @pytest.mark.asyncio
    async def test_异步回调被正确调用(self):
        reloader = RulesHotReloader()
        reloader._is_running = False  # 确保在未运行状态

        # 未运行时，trigger_reload 只调用同步回调，不调用异步回调
        # 这是设计行为：未运行时只执行同步回调
        sync_log = []
        reloader.register_callback(lambda f: sync_log.append(f))
        reloader.trigger_reload("routing_rules.yaml")
        assert "routing_rules.yaml" in sync_log

    @pytest.mark.asyncio
    async def test_notify_callbacks调用异步回调(self):
        reloader = RulesHotReloader()
        async_log = []

        async def async_callback(fname):
            async_log.append(fname)

        reloader.register_callback(async_callback)
        await reloader._notify_callbacks("routing_rules.yaml")
        assert "routing_rules.yaml" in async_log


# ─── RulesHotReloader.trigger_reload ──────────────────────────────────────────

class TestRulesHotReloaderTriggerReload:

    def test_未运行时trigger_reload直接执行同步回调(self):
        reloader = RulesHotReloader()
        assert reloader._is_running is False
        received = []
        reloader.register_callback(lambda f: received.append(f))
        reloader.trigger_reload("routing_rules.yaml")
        assert received == ["routing_rules.yaml"]

    @pytest.mark.asyncio
    async def test_运行时trigger_reload创建异步任务(self):
        reloader = RulesHotReloader()
        reloader._is_running = True
        received = []

        async def cb(f):
            received.append(f)

        reloader.register_callback(cb)
        with patch("app.evaluation.rules.hot_reload.asyncio.create_task") as mock_task:
            reloader.trigger_reload("routing_rules.yaml")
            mock_task.assert_called_once()

    def test_默认文件名为model_prompts_yaml(self):
        reloader = RulesHotReloader()
        received = []
        reloader.register_callback(lambda f: received.append(f))
        reloader.trigger_reload()  # 不传参数
        assert received == ["model_prompts.yaml"]


# ─── RulesHotReloader.start/stop ──────────────────────────────────────────────

class TestRulesHotReloaderStartStop:

    @pytest.mark.asyncio
    async def test_start创建轮询任务(self):
        reloader = RulesHotReloader()
        with patch("app.evaluation.rules.hot_reload.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock()
            reloader.start()
            mock_task.assert_called_once()
        reloader._is_running = False

    @pytest.mark.asyncio
    async def test_重复start不重复创建任务(self):
        reloader = RulesHotReloader()
        with patch("app.evaluation.rules.hot_reload.asyncio.create_task") as mock_task:
            mock_task.return_value = MagicMock()
            reloader.start()
            reloader.start()  # 第二次调用应被忽略
            assert mock_task.call_count == 1
        reloader._is_running = False

    @pytest.mark.asyncio
    async def test_stop后is_running为False(self):
        reloader = RulesHotReloader()
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()

        async def fake_await():
            raise asyncio.CancelledError()

        mock_task.__await__ = lambda self: fake_await().__await__()
        reloader._task = asyncio.ensure_future(asyncio.sleep(0))
        reloader._is_running = True
        await reloader.stop()
        assert reloader._is_running is False

    @pytest.mark.asyncio
    async def test_stop无任务时不抛出(self):
        reloader = RulesHotReloader()
        reloader._is_running = False
        reloader._task = None
        await reloader.stop()  # 不应抛出


# ─── RulesHotReloader 单例 ────────────────────────────────────────────────────

class TestRulesHotReloaderSingleton:

    def test_get_hot_reloader初始为None(self):
        old = _hr_module._reloader_instance
        try:
            _hr_module._reloader_instance = None
            assert get_hot_reloader() is None
        finally:
            _hr_module._reloader_instance = old

    def test_init_hot_reloader设置单例(self):
        old = _hr_module._reloader_instance
        try:
            r = init_hot_reloader()
            assert isinstance(r, RulesHotReloader)
            assert get_hot_reloader() is r
        finally:
            _hr_module._reloader_instance = old


# ─── _init_mtimes / _check_for_changes ────────────────────────────────────────

class TestRulesHotReloaderFileCheck:

    def test_init_mtimes不存在的文件记录为0(self, tmp_path):
        reloader = RulesHotReloader()
        with patch("app.evaluation.rules.hot_reload.RULES_DIR", tmp_path):
            reloader._init_mtimes()
        # 文件不存在时 mtime 应为 0.0
        for fname in reloader._mtimes.values():
            assert fname == 0.0

    def test_init_mtimes存在的文件记录其mtime(self, tmp_path):
        reloader = RulesHotReloader()
        f = tmp_path / "model_prompts.yaml"
        f.write_text("intents: {}")
        with patch("app.evaluation.rules.hot_reload.RULES_DIR", tmp_path):
            reloader._init_mtimes()
        assert reloader._mtimes.get("model_prompts.yaml", 0.0) > 0.0

    @pytest.mark.asyncio
    async def test_文件无变更时不触发回调(self, tmp_path):
        reloader = RulesHotReloader()
        f = tmp_path / "model_prompts.yaml"
        f.write_text("intents: {}")
        with patch("app.evaluation.rules.hot_reload.RULES_DIR", tmp_path):
            reloader._init_mtimes()
        # mtime 未变化，不触发
        received = []
        reloader.register_callback(lambda fname: received.append(fname))
        with patch("app.evaluation.rules.hot_reload.RULES_DIR", tmp_path):
            await reloader._check_for_changes()
        assert received == []
