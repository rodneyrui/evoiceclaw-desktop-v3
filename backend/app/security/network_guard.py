"""NetworkGuard — 网络域名白名单守卫

宪法第8条：每个工作区维护域名白名单，网络工具只能访问白名单内域名。
逻辑层2.1：网络请求须经 NetworkGuard 过滤。

功能:
- check_url(): 检查 URL 是否在工作区白名单内
- get_whitelist(): 获取工作区域名白名单
- add_to_whitelist() / remove_from_whitelist(): 管理白名单
"""

import logging
from urllib.parse import urlparse

from app.core.config import load_config

logger = logging.getLogger("evoiceclaw.security.network_guard")

# 云元数据服务地址（必须无条件拦截）
_BLOCKED_HOSTS = frozenset([
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.google.com",
])


def check_url(url: str, workspace_id: str = "global") -> tuple[bool, str]:
    """检查 URL 是否允许访问

    Args:
        url: 完整 URL
        workspace_id: 工作区 ID

    Returns:
        (allowed, reason) — allowed=True 表示允许
    """
    # 解析 URL
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except Exception:
        return False, "URL 解析失败"

    if not hostname:
        return False, "无法从 URL 提取域名"

    # 检查云元数据地址（无条件拦截）
    if hostname in _BLOCKED_HOSTS:
        return False, f"禁止访问云元数据服务: {hostname}"

    # 检查内网地址
    from app.kernel.tools.builtin.network import _is_private_host
    if _is_private_host(hostname):
        return False, f"禁止访问内网地址: {hostname}"

    # 获取配置
    config = load_config()
    ng_config = config.get("network_guard", {})

    # NetworkGuard 未启用时放行
    if not ng_config.get("enabled", False):
        return True, "NetworkGuard 未启用，放行"

    # 获取白名单：全局默认 + 工作区级别
    whitelist = set(ng_config.get("default_whitelist", []))

    # 获取工作区级别白名单
    ws_whitelist = _get_workspace_whitelist(workspace_id)
    whitelist.update(ws_whitelist)

    # 空白名单 = 允许所有（尚未配置阶段）
    if not whitelist:
        return True, "白名单为空，默认放行"

    # 检查域名是否在白名单中（支持子域名匹配）
    for allowed_domain in whitelist:
        if hostname == allowed_domain or hostname.endswith("." + allowed_domain):
            return True, f"域名 {hostname} 在白名单中"

    return False, f"域名 {hostname} 不在工作区白名单内（workspace={workspace_id}）"


def get_whitelist(workspace_id: str = "global") -> list[str]:
    """获取工作区的完整域名白名单（全局 + 工作区级别）"""
    config = load_config()
    ng_config = config.get("network_guard", {})

    whitelist = list(ng_config.get("default_whitelist", []))
    ws_whitelist = _get_workspace_whitelist(workspace_id)

    # 合并去重
    seen = set(whitelist)
    for domain in ws_whitelist:
        if domain not in seen:
            whitelist.append(domain)
            seen.add(domain)

    return whitelist


def add_to_whitelist(domain: str, workspace_id: str = "global") -> bool:
    """添加域名到工作区白名单

    Returns:
        True 表示添加成功
    """
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        ws = ws_svc.get_workspace(workspace_id)
        if not ws:
            logger.warning("[NetworkGuard] 工作区不存在: %s", workspace_id)
            return False

        current = list(getattr(ws, "network_whitelist", []) or [])
        if domain not in current:
            current.append(domain)
            ws_svc.update_workspace_field(workspace_id, "network_whitelist", current)
            logger.info("[NetworkGuard] 添加白名单: %s → workspace=%s", domain, workspace_id)
        return True
    except Exception as e:
        logger.warning("[NetworkGuard] 添加白名单失败: %s", e)
        return False


def remove_from_whitelist(domain: str, workspace_id: str = "global") -> bool:
    """从工作区白名单中移除域名"""
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        ws = ws_svc.get_workspace(workspace_id)
        if not ws:
            return False

        current = list(getattr(ws, "network_whitelist", []) or [])
        if domain in current:
            current.remove(domain)
            ws_svc.update_workspace_field(workspace_id, "network_whitelist", current)
            logger.info("[NetworkGuard] 移除白名单: %s ← workspace=%s", domain, workspace_id)
        return True
    except Exception as e:
        logger.warning("[NetworkGuard] 移除白名单失败: %s", e)
        return False


def _get_workspace_whitelist(workspace_id: str) -> list[str]:
    """获取工作区级别的白名单"""
    if workspace_id == "global":
        return []
    try:
        from app.services.workspace_service import get_workspace_service
        ws_svc = get_workspace_service()
        ws = ws_svc.get_workspace(workspace_id)
        if ws:
            return list(getattr(ws, "network_whitelist", []) or [])
    except Exception as e:
        logger.debug("[NetworkGuard] 获取工作区白名单失败: %s", e)
    return []
