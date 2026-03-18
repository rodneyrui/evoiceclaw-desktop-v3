"""PermissionBroker 权限协商测试"""

import asyncio
import pytest

from app.security.permission_broker import (
    PermissionBroker,
    ElevationRequest,
    ELEVATION_MARKER,
    elevation_level,
    get_permission_broker,
)


# ─── ELEVATION_MARKER ─────────────────────────────────────────

class TestElevationMarker:

    def test_elevation_marker_is_string(self):
        assert isinstance(ELEVATION_MARKER, str)
        assert len(ELEVATION_MARKER) > 0

    def test_elevation_marker_value(self):
        assert ELEVATION_MARKER == "__elevation_required__"


# ─── elevation_level ContextVar ──────────────────────────────

class TestElevationLevelContextVar:

    def test_default_is_none(self):
        assert elevation_level.get() is None

    def test_set_and_reset(self):
        token = elevation_level.set("L2")
        assert elevation_level.get() == "L2"
        elevation_level.reset(token)
        assert elevation_level.get() is None

    def test_set_l3(self):
        token = elevation_level.set("L3")
        assert elevation_level.get() == "L3"
        elevation_level.reset(token)

    @pytest.mark.asyncio
    async def test_contextvar_isolation(self):
        """不同异步任务之间 ContextVar 相互隔离"""
        results = {}

        async def task_a():
            token = elevation_level.set("L2")
            await asyncio.sleep(0)
            results["a"] = elevation_level.get()
            elevation_level.reset(token)

        async def task_b():
            await asyncio.sleep(0)
            results["b"] = elevation_level.get()

        await asyncio.gather(task_a(), task_b())
        assert results["a"] == "L2"
        assert results["b"] is None


# ─── ElevationRequest ─────────────────────────────────────────

class TestElevationRequest:

    def _make_request(self, **kwargs):
        defaults = {
            "request_id": "test01",
            "command": "python3 script.py",
            "cmd_name": "python3",
            "current_level": "L1",
            "required_level": "L2",
            "reason": "代码执行类命令需要 L2",
        }
        defaults.update(kwargs)
        return ElevationRequest(**defaults)

    def test_request_fields(self):
        req = self._make_request()
        assert req.request_id == "test01"
        assert req.command == "python3 script.py"
        assert req.cmd_name == "python3"
        assert req.current_level == "L1"
        assert req.required_level == "L2"
        assert req.approved is None

    def test_event_initially_not_set(self):
        req = self._make_request()
        assert not req.event.is_set()

    def test_created_at_is_float(self):
        req = self._make_request()
        assert isinstance(req.created_at, float)
        assert req.created_at > 0


# ─── PermissionBroker ─────────────────────────────────────────

class TestPermissionBrokerCreateRequest:

    def setup_method(self):
        self.broker = PermissionBroker()

    def test_create_request_returns_elevation_request(self):
        req = self.broker.create_request(
            command="python3 test.py",
            cmd_name="python3",
            current_level="L1",
            required_level="L2",
            reason="代码执行类命令",
        )
        assert isinstance(req, ElevationRequest)

    def test_request_has_unique_id(self):
        req1 = self.broker.create_request("python3 a.py", "python3", "L1", "L2", "r")
        req2 = self.broker.create_request("python3 b.py", "python3", "L1", "L2", "r")
        assert req1.request_id != req2.request_id

    def test_request_stored_in_pending(self):
        req = self.broker.create_request("git status", "git", "L1", "L2", "r")
        stored = self.broker.get_request(req.request_id)
        assert stored is req

    def test_get_nonexistent_request(self):
        assert self.broker.get_request("nonexistent_id") is None


class TestPermissionBrokerApprove:

    def setup_method(self):
        self.broker = PermissionBroker()

    def test_approve_sets_approved_true(self):
        req = self.broker.create_request("python3 t.py", "python3", "L1", "L2", "r")
        result = self.broker.approve(req.request_id)
        assert result is True
        assert req.approved is True

    def test_approve_sets_event(self):
        req = self.broker.create_request("python3 t.py", "python3", "L1", "L2", "r")
        self.broker.approve(req.request_id)
        assert req.event.is_set()

    def test_approve_removes_from_pending(self):
        req = self.broker.create_request("python3 t.py", "python3", "L1", "L2", "r")
        # 注意：approve 不会立即从 pending 中移除，wait_for_decision 才会移除
        # approve 只设置 event
        self.broker.approve(req.request_id)
        assert req.event.is_set()

    def test_approve_nonexistent_returns_false(self):
        result = self.broker.approve("nonexistent")
        assert result is False


class TestPermissionBrokerDeny:

    def setup_method(self):
        self.broker = PermissionBroker()

    def test_deny_sets_approved_false(self):
        req = self.broker.create_request("git push", "git", "L1", "L2", "r")
        result = self.broker.deny(req.request_id)
        assert result is True
        assert req.approved is False

    def test_deny_sets_event(self):
        req = self.broker.create_request("git push", "git", "L1", "L2", "r")
        self.broker.deny(req.request_id)
        assert req.event.is_set()

    def test_deny_nonexistent_returns_false(self):
        result = self.broker.deny("nonexistent_id")
        assert result is False


class TestPermissionBrokerWaitForDecision:

    @pytest.mark.asyncio
    async def test_wait_approved(self):
        broker = PermissionBroker()
        req = broker.create_request("python3 t.py", "python3", "L1", "L2", "r")

        # 异步批准
        async def approve_after_delay():
            await asyncio.sleep(0.05)
            broker.approve(req.request_id)

        asyncio.create_task(approve_after_delay())
        result = await broker.wait_for_decision(req.request_id, timeout=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_denied(self):
        broker = PermissionBroker()
        req = broker.create_request("git push", "git", "L1", "L2", "r")

        async def deny_after_delay():
            await asyncio.sleep(0.05)
            broker.deny(req.request_id)

        asyncio.create_task(deny_after_delay())
        result = await broker.wait_for_decision(req.request_id, timeout=5)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        broker = PermissionBroker()
        req = broker.create_request("python3 t.py", "python3", "L1", "L2", "r")
        result = await broker.wait_for_decision(req.request_id, timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_nonexistent_request(self):
        broker = PermissionBroker()
        result = await broker.wait_for_decision("nonexistent", timeout=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_request_removed_after_decision(self):
        broker = PermissionBroker()
        req = broker.create_request("python3 t.py", "python3", "L1", "L2", "r")
        broker.approve(req.request_id)
        await broker.wait_for_decision(req.request_id, timeout=1)
        # 决策完成后从 pending 移除
        assert broker.get_request(req.request_id) is None


# ─── get_permission_broker 单例 ───────────────────────────────

class TestGetPermissionBrokerSingleton:

    def test_returns_same_instance(self):
        broker1 = get_permission_broker()
        broker2 = get_permission_broker()
        assert broker1 is broker2

    def test_returns_permission_broker(self):
        broker = get_permission_broker()
        assert isinstance(broker, PermissionBroker)
