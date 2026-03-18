"""API 依赖注入"""

from fastapi import Request


async def get_config(request: Request) -> dict:
    """从 app.state 获取配置"""
    return request.app.state.config
