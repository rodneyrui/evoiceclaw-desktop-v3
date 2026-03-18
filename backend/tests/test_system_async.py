"""异步测试系统API函数"""

import pytest
import asyncio
from app.api.v1.system import health_check


@pytest.mark.asyncio
async def test_health_check_direct():
    """直接测试健康检查函数"""
    result = await health_check()
    
    assert isinstance(result, dict)
    assert result["status"] == "ok"
    assert result["version"] == "3.0.0"


@pytest.mark.asyncio
async def test_health_check_structure():
    """测试健康检查数据结构"""
    result = await health_check()
    
    # 检查所有字段
    assert set(result.keys()) == {"status", "version"}
    
    # 检查字段类型
    assert isinstance(result["status"], str)
    assert isinstance(result["version"], str)
    
    # 检查字段值
    assert result["status"] == "ok"
    assert result["version"] == "3.0.0"


def test_health_check_async():
    """测试健康检查函数是异步的"""
    import inspect
    assert inspect.iscoroutinefunction(health_check)


def test_system_router_import():
    """测试系统路由导入"""
    from app.api.v1.system import router
    assert router is not None
    assert router.prefix == "/system"
    assert router.tags == ["system"]


def test_logger_initialization():
    """测试日志记录器"""
    import logging
    logger = logging.getLogger("evoiceclaw.api.system")
    assert logger.name == "evoiceclaw.api.system"


def test_module_docstring():
    """测试模块文档字符串"""
    import app.api.v1.system as system_module
    assert system_module.__doc__ is not None
    assert "系统端点" in system_module.__doc__


def test_health_check_function_docstring():
    """测试健康检查函数文档字符串"""
    assert health_check.__doc__ is not None
    assert "健康检查端点" in health_check.__doc__


@pytest.mark.asyncio
async def test_multiple_health_checks():
    """测试多次健康检查"""
    for i in range(3):
        result = await health_check()
        assert result["status"] == "ok"
        assert result["version"] == "3.0.0"