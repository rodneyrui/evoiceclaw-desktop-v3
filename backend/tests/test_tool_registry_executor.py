"""工具注册中心与执行器测试

覆盖：
- _validate_arguments（必填缺失 / 类型检查 / SA-11 bool拒绝 / enum 校验 / 通过）
- ToolRegistry（register/unregister/get/get_all/tools_json_for_llm/tools_json_for_model/build_capability_declaration/单例）
- ToolExecutor（未知工具 / 权限拒绝 / Schema 校验失败 / 超时 / 执行成功 / execute_all）
- 文件系统工具 _is_safe_path + ReadFileTool + WriteFileTool + EditFileTool
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.domain.models import ToolCall
from app.kernel.tools.executor import _validate_arguments, ToolExecutor
from app.kernel.tools.registry import ToolRegistry, init_tool_registry, get_tool_registry
from app.kernel.tools.protocol import SkillProtocol
import app.kernel.tools.registry as _registry_module


# ─── 测试用 Skill 实现 ─────────────────────────────────────────────────────

class _EchoTool(SkillProtocol):
    """测试用工具，原样返回 message 参数"""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "返回输入消息"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "flag": {"type": "boolean"},
                "tags": {"type": "array"},
                "meta": {"type": "object"},
                "mode": {"type": "string", "enum": ["fast", "slow"]},
            },
            "required": ["message"],
        }

    @property
    def capability_brief(self) -> str:
        return "原样返回 message"

    @property
    def required_permissions(self) -> list[str]:
        return ["echo"]

    async def execute(self, arguments: dict) -> str:
        return arguments.get("message", "")


class _HiddenTool(SkillProtocol):
    """supports_llm_calling=False 的工具"""

    @property
    def name(self) -> str:
        return "hidden"

    @property
    def description(self) -> str:
        return "隐藏工具"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def supports_llm_calling(self) -> bool:
        return False

    async def execute(self, arguments: dict) -> str:
        return "hidden"


# ─── _validate_arguments ────────────────────────────────────────────────────

class TestValidateArguments:

    def _schema(self, **props):
        return {
            "type": "object",
            "properties": props,
            "required": list(props.keys()),
        }

    def test_通过_所有必填参数存在(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        assert _validate_arguments({"name": "test"}, schema) is None

    def test_缺少必填参数返回错误(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        err = _validate_arguments({}, schema)
        assert err is not None
        assert "name" in err

    def test_缺少多个必填参数错误信息包含所有缺失字段(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }
        err = _validate_arguments({}, schema)
        assert "a" in err
        assert "b" in err

    def test_字符串类型检查通过(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        assert _validate_arguments({"x": "hello"}, schema) is None

    def test_整数类型检查通过(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        assert _validate_arguments({"n": 5}, schema) is None

    def test_字符串传整数类型不匹配返回错误(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        err = _validate_arguments({"x": 42}, schema)
        assert err is not None
        assert "x" in err

    def test_SA11_bool传给integer被拒绝(self):
        """bool 是 int 子类，integer 类型必须显式拒绝 bool"""
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        err = _validate_arguments({"n": True}, schema)
        assert err is not None
        assert "boolean" in err

    def test_SA11_bool传给number被拒绝(self):
        schema = {"type": "object", "properties": {"r": {"type": "number"}}, "required": ["r"]}
        err = _validate_arguments({"r": False}, schema)
        assert err is not None

    def test_bool类型本身通过(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}, "required": ["flag"]}
        assert _validate_arguments({"flag": True}, schema) is None

    def test_array类型通过(self):
        schema = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
        assert _validate_arguments({"items": [1, 2, 3]}, schema) is None

    def test_enum值在允许范围内通过(self):
        schema = {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}},
            "required": ["mode"],
        }
        assert _validate_arguments({"mode": "fast"}, schema) is None

    def test_enum值不在允许范围内返回错误(self):
        schema = {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}},
            "required": ["mode"],
        }
        err = _validate_arguments({"mode": "turbo"}, schema)
        assert err is not None
        assert "turbo" in err

    def test_未知参数被忽略不报错(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        assert _validate_arguments({"a": "ok", "extra": "ignored"}, schema) is None

    def test_无required字段schema通过(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert _validate_arguments({}, schema) is None


# ─── ToolRegistry ────────────────────────────────────────────────────────────

class TestToolRegistry:

    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _EchoTool()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_get_未注册返回None(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_unregister_返回True(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        assert reg.unregister("echo") is True

    def test_unregister_不存在返回False(self):
        reg = ToolRegistry()
        assert reg.unregister("nonexistent") is False

    def test_get_all返回所有工具(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        reg.register(_HiddenTool())
        assert len(reg.get_all()) == 2

    def test_tools_json_for_llm只返回supports_llm_calling为True的工具(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())     # supports_llm_calling=True
        reg.register(_HiddenTool())   # supports_llm_calling=False
        result = reg.tools_json_for_llm()
        names = [t["function"]["name"] for t in result]
        assert "echo" in names
        assert "hidden" not in names

    def test_tools_json_for_llm格式正确(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        result = reg.tools_json_for_llm()
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert "name" in result[0]["function"]
        assert "description" in result[0]["function"]
        assert "parameters" in result[0]["function"]

    def test_tools_json_for_model无规则时返回全量(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with patch.object(reg, "_get_allowed_tools", return_value=None):
            result = reg.tools_json_for_model("any/model")
        assert len(result) == 1

    def test_tools_json_for_model空规则返回空列表(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with patch.object(reg, "_get_allowed_tools", return_value=[]):
            result = reg.tools_json_for_model("restricted/model")
        assert result == []

    def test_tools_json_for_model按允许列表过滤(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with patch.object(reg, "_get_allowed_tools", return_value=["echo"]):
            result = reg.tools_json_for_model("any/model")
        assert len(result) == 1

    def test_build_capability_declaration包含工具简述(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        decl = reg.build_capability_declaration()
        assert "echo" in decl
        assert "原样返回" in decl

    def test_build_capability_declaration空注册表返回空字符串(self):
        reg = ToolRegistry()
        assert reg.build_capability_declaration() == ""

    def test_单例未初始化抛出RuntimeError(self):
        old = _registry_module._registry
        try:
            _registry_module._registry = None
            with pytest.raises(RuntimeError, match="未初始化"):
                get_tool_registry()
        finally:
            _registry_module._registry = old

    def test_init_tool_registry设置单例(self):
        old = _registry_module._registry
        try:
            reg = init_tool_registry()
            assert isinstance(reg, ToolRegistry)
            assert get_tool_registry() is reg
        finally:
            _registry_module._registry = old


# ─── ToolExecutor ────────────────────────────────────────────────────────────

class TestToolExecutor:

    def _make_executor(self) -> ToolExecutor:
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with patch("app.kernel.tools.executor.log_event"):
            return ToolExecutor(reg)

    def _tc(self, name: str, arguments: dict, tc_id: str = "tc-1") -> ToolCall:
        return ToolCall(id=tc_id, name=name, arguments=arguments)

    @pytest.mark.asyncio
    async def test_未知工具返回错误消息(self):
        executor = self._make_executor()
        tc = self._tc("nonexistent_tool", {})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc)
        assert call_id == "tc-1"
        assert "未知工具" in result

    @pytest.mark.asyncio
    async def test_权限检查失败返回错误(self):
        executor = self._make_executor()
        tc = self._tc("echo", {"message": "hi"})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc, caller_permissions=[])
        assert "权限" in result

    @pytest.mark.asyncio
    async def test_caller_permissions为None跳过权限检查(self):
        executor = self._make_executor()
        tc = self._tc("echo", {"message": "hi"})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc, caller_permissions=None)
        assert result == "hi"

    @pytest.mark.asyncio
    async def test_Schema校验失败返回错误(self):
        executor = self._make_executor()
        # echo 工具 required=["message"]，不传 message
        tc = self._tc("echo", {})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc)
        assert "参数" in result or "缺少" in result

    @pytest.mark.asyncio
    async def test_执行成功返回结果(self):
        executor = self._make_executor()
        tc = self._tc("echo", {"message": "hello world"})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc)
        assert call_id == "tc-1"
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_执行超时返回超时错误(self):
        reg = ToolRegistry()

        class _SlowTool(_EchoTool):
            @property
            def tool_timeout(self) -> int:
                return 1

            async def execute(self, arguments: dict) -> str:
                await asyncio.sleep(10)
                return "never"

        reg.register(_SlowTool())
        executor = ToolExecutor(reg)
        tc = self._tc("echo", {"message": "test"})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc)
        assert "超时" in result

    @pytest.mark.asyncio
    async def test_执行异常返回错误消息(self):
        reg = ToolRegistry()

        class _BrokenTool(_EchoTool):
            async def execute(self, arguments: dict) -> str:
                raise ValueError("something went wrong")

        reg.register(_BrokenTool())
        executor = ToolExecutor(reg)
        tc = self._tc("echo", {"message": "test"})
        with patch("app.kernel.tools.executor.log_event"):
            call_id, result = await executor.execute(tc)
        assert "出错" in result

    @pytest.mark.asyncio
    async def test_execute_all顺序执行多个工具(self):
        executor = self._make_executor()
        tcs = [
            self._tc("echo", {"message": "a"}, "tc-1"),
            self._tc("echo", {"message": "b"}, "tc-2"),
        ]
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all(tcs)
        assert len(results) == 2
        assert results[0] == ("tc-1", "a")
        assert results[1] == ("tc-2", "b")


class TestExecuteAllParallel:
    """execute_all 并行执行测试"""

    def _make_executor(self) -> ToolExecutor:
        reg = ToolRegistry()
        reg.register(_EchoTool())
        with patch("app.kernel.tools.executor.log_event"):
            return ToolExecutor(reg)

    def _tc(self, name: str, arguments: dict, tc_id: str = "tc-1") -> ToolCall:
        return ToolCall(id=tc_id, name=name, arguments=arguments)

    @pytest.mark.asyncio
    async def test_多工具并行执行返回正确结果(self):
        """多个工具调用应并行执行且结果顺序与输入一致"""
        executor = self._make_executor()
        tcs = [
            self._tc("echo", {"message": "first"}, "tc-1"),
            self._tc("echo", {"message": "second"}, "tc-2"),
            self._tc("echo", {"message": "third"}, "tc-3"),
        ]
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all(tcs)
        assert len(results) == 3
        assert results[0] == ("tc-1", "first")
        assert results[1] == ("tc-2", "second")
        assert results[2] == ("tc-3", "third")

    @pytest.mark.asyncio
    async def test_单工具失败不影响其他工具(self):
        """execute() 内部捕获异常，单个工具失败返回错误字符串，不影响其他"""
        reg = ToolRegistry()
        reg.register(_EchoTool())

        class _FailTool(SkillProtocol):
            @property
            def name(self) -> str:
                return "fail"
            @property
            def description(self) -> str:
                return "总是失败"
            @property
            def parameters_schema(self) -> dict:
                return {"type": "object", "properties": {}}
            async def execute(self, arguments: dict) -> str:
                raise RuntimeError("boom")

        reg.register(_FailTool())
        with patch("app.kernel.tools.executor.log_event"):
            executor = ToolExecutor(reg)

        tcs = [
            self._tc("echo", {"message": "ok"}, "tc-1"),
            self._tc("fail", {}, "tc-2"),
            self._tc("echo", {"message": "also ok"}, "tc-3"),
        ]
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all(tcs)
        assert len(results) == 3
        assert results[0] == ("tc-1", "ok")
        assert "出错" in results[1][1]
        assert results[2] == ("tc-3", "also ok")

    @pytest.mark.asyncio
    async def test_单个工具走顺序路径(self):
        """只有一个工具调用时不走 asyncio.gather"""
        executor = self._make_executor()
        tcs = [self._tc("echo", {"message": "solo"}, "tc-1")]
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all(tcs)
        assert len(results) == 1
        assert results[0] == ("tc-1", "solo")

    @pytest.mark.asyncio
    async def test_空列表返回空结果(self):
        executor = self._make_executor()
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_并行执行确实并发(self):
        """验证多个慢工具并行执行时总耗时接近单个而非累加"""
        reg = ToolRegistry()

        class _SlowEcho(SkillProtocol):
            @property
            def name(self) -> str:
                return "slow_echo"
            @property
            def description(self) -> str:
                return "慢速回显"
            @property
            def parameters_schema(self) -> dict:
                return {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}
            async def execute(self, arguments: dict) -> str:
                await asyncio.sleep(0.3)
                return arguments["msg"]

        reg.register(_SlowEcho())
        with patch("app.kernel.tools.executor.log_event"):
            executor = ToolExecutor(reg)

        tcs = [
            self._tc("slow_echo", {"msg": "a"}, "tc-1"),
            self._tc("slow_echo", {"msg": "b"}, "tc-2"),
            self._tc("slow_echo", {"msg": "c"}, "tc-3"),
        ]
        import time
        start = time.monotonic()
        with patch("app.kernel.tools.executor.log_event"):
            results = await executor.execute_all(tcs)
        elapsed = time.monotonic() - start

        assert len(results) == 3
        assert results[0] == ("tc-1", "a")
        assert results[1] == ("tc-2", "b")
        assert results[2] == ("tc-3", "c")
        # 串行需 0.9s，并行应 < 0.6s
        assert elapsed < 0.6, f"并行执行耗时 {elapsed:.2f}s，预期 < 0.6s"


# ─── _is_safe_path ────────────────────────────────────────────────────────────

class TestIsSafePath:

    def test_路径在授权根目录内返回True(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import _is_safe_path
        target = tmp_path / "subdir" / "file.txt"
        assert _is_safe_path(target, [tmp_path]) is True

    def test_路径不在任何根目录内返回False(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import _is_safe_path
        other = tmp_path / "other"
        allowed = [tmp_path / "allowed"]
        assert _is_safe_path(other, allowed) is False

    def test_空根目录列表返回False(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import _is_safe_path
        assert _is_safe_path(tmp_path / "file.txt", []) is False

    def test_系统目录被阻止(self):
        from app.kernel.tools.builtin.filesystem import _is_safe_path
        import platform
        if platform.system() != "Linux":
            # /etc 在 macOS 也应被阻止
            target = Path("/etc/passwd")
            # 即使 /etc 在 allowed_roots 里，BLOCKED_PREFIXES 会拦截
            assert _is_safe_path(target, [Path("/etc")]) is False


# ─── ReadFileTool ─────────────────────────────────────────────────────────────

class TestReadFileTool:

    @pytest.mark.asyncio
    async def test_无路径参数返回错误(self):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        tool = ReadFileTool()
        result = await tool.execute({})
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_路径不安全返回拒绝消息(self):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        tool = ReadFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=False):
            result = await tool.execute({"path": "/etc/passwd"})
        assert "拒绝" in result

    @pytest.mark.asyncio
    async def test_文件不存在返回提示(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        tool = ReadFileTool()
        nonexistent = tmp_path / "nonexistent.txt"
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(nonexistent)})
        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_路径是目录返回提示使用list_directory(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        tool = ReadFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(tmp_path)})
        assert "list_directory" in result

    @pytest.mark.asyncio
    async def test_读取文件返回内容(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        tool = ReadFileTool()
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(f)})
        assert "hello world" in result

    def test_工具名称为read_file(self):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        assert ReadFileTool().name == "read_file"

    def test_required_permissions包含read_file(self):
        from app.kernel.tools.builtin.filesystem import ReadFileTool
        assert "read_file" in ReadFileTool().required_permissions


# ─── WriteFileTool ────────────────────────────────────────────────────────────

class TestWriteFileTool:

    @pytest.mark.asyncio
    async def test_无路径参数返回错误(self):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        tool = WriteFileTool()
        result = await tool.execute({})
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_路径不安全返回拒绝消息(self):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        tool = WriteFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=False):
            result = await tool.execute({"path": "/etc/evil.sh", "content": "rm -rf"})
        assert "拒绝" in result

    @pytest.mark.asyncio
    async def test_禁止写入sh脚本(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        tool = WriteFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(tmp_path / "run.sh"), "content": "echo hi"})
        assert "安全限制" in result

    @pytest.mark.asyncio
    async def test_禁止写入exe文件(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        tool = WriteFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(tmp_path / "virus.exe"), "content": "binary"})
        assert "安全限制" in result

    @pytest.mark.asyncio
    async def test_写入txt文件成功(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        tool = WriteFileTool()
        f = tmp_path / "note.txt"
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({"path": str(f), "content": "test content"})
        assert "已写入" in result
        assert f.read_text() == "test content"

    def test_工具名称为write_file(self):
        from app.kernel.tools.builtin.filesystem import WriteFileTool
        assert WriteFileTool().name == "write_file"


# ─── EditFileTool ─────────────────────────────────────────────────────────────

class TestEditFileTool:

    @pytest.mark.asyncio
    async def test_无路径参数返回错误(self):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        result = await tool.execute({"old_string": "x", "new_string": "y"})
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_无old_string参数返回错误(self):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        result = await tool.execute({"path": "/tmp/f.txt", "new_string": "y"})
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_old_string等于new_string返回错误(self):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        result = await tool.execute({
            "path": "/tmp/f.txt", "old_string": "same", "new_string": "same"
        })
        assert "相同" in result

    @pytest.mark.asyncio
    async def test_路径不安全返回拒绝(self):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=False):
            result = await tool.execute({
                "path": "/etc/passwd", "old_string": "root", "new_string": "evil"
            })
        assert "拒绝" in result

    @pytest.mark.asyncio
    async def test_禁止编辑sh文件(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        f = tmp_path / "run.sh"
        f.write_text("echo hello")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(f), "old_string": "echo hello", "new_string": "rm -rf /"
            })
        assert "安全限制" in result

    @pytest.mark.asyncio
    async def test_文件不存在返回提示(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(tmp_path / "nonexistent.txt"),
                "old_string": "x", "new_string": "y",
            })
        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_old_string不存在返回提示(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        f = tmp_path / "file.txt"
        f.write_text("hello world")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(f), "old_string": "NOTFOUND", "new_string": "replaced",
            })
        assert "未找到" in result

    @pytest.mark.asyncio
    async def test_old_string不唯一返回提示(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        f = tmp_path / "file.txt"
        f.write_text("abc abc abc")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(f), "old_string": "abc", "new_string": "xyz",
            })
        assert "3" in result  # 找到3处匹配

    @pytest.mark.asyncio
    async def test_单次替换成功(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        f = tmp_path / "note.txt"
        f.write_text("Hello World")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(f), "old_string": "World", "new_string": "Python",
            })
        assert "编辑成功" in result
        assert f.read_text() == "Hello Python"

    @pytest.mark.asyncio
    async def test_replace_all替换所有匹配(self, tmp_path):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        tool = EditFileTool()
        f = tmp_path / "note.txt"
        f.write_text("a b a b a")
        with patch("app.kernel.tools.builtin.filesystem._is_safe_path", return_value=True):
            result = await tool.execute({
                "path": str(f), "old_string": "a", "new_string": "X", "replace_all": True,
            })
        assert "编辑成功" in result
        assert f.read_text() == "X b X b X"

    def test_工具名称为edit_file(self):
        from app.kernel.tools.builtin.filesystem import EditFileTool
        assert EditFileTool().name == "edit_file"
