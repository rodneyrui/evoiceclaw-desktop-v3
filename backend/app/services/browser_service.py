"""BrowserService — 托管浏览器服务

Agent 调用 web_fetch/http_request 后，自动在本机打开浏览器展示网页。
用户作为旁观者无需任何点击。

支持：
- macOS: subprocess.Popen(["open", url])
- Linux: subprocess.Popen(["xdg-open", url])
- SSH 远程会话自动检测（不打开）
- 同一 URL 5 秒去重节流
- 预留 Playwright 接口
"""

import logging
import os
import platform
import subprocess
import time

logger = logging.getLogger("evoiceclaw.browser")

_instance: "BrowserService | None" = None


class BrowserService:
    """托管浏览器管理器"""

    def __init__(self, config: dict) -> None:
        browser_cfg = config.get("browser", {})
        self._auto_open: bool = browser_cfg.get("auto_open", True)
        self._remote_mode: bool = browser_cfg.get("remote_mode", False)
        self._system = platform.system()  # "Darwin" / "Linux" / "Windows"

        # SSH 远程会话自动检测
        self._is_ssh = bool(os.environ.get("SSH_CONNECTION"))

        # 去重节流：{url: last_open_time}
        self._recent_urls: dict[str, float] = {}
        self._dedup_seconds = 5.0

        # 综合判断是否启用
        self._enabled = self._auto_open and not self._remote_mode and not self._is_ssh

        if self._is_ssh:
            logger.info("浏览器服务: 检测到 SSH 远程会话，自动禁用浏览器打开")
        elif self._remote_mode:
            logger.info("浏览器服务: remote_mode=true，浏览器打开已禁用")

        logger.info(
            "浏览器服务初始化完成 (enabled=%s, system=%s)",
            self._enabled, self._system,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def open_url(self, url: str) -> bool:
        """打开浏览器访问指定 URL

        Returns:
            True 如果成功触发打开，False 如果被跳过（禁用/去重/失败）
        """
        if not self._enabled:
            return False

        if not url or not url.startswith(("http://", "https://")):
            return False

        # 去重节流：同一 URL 5 秒内不重复打开
        now = time.time()
        last_time = self._recent_urls.get(url, 0)
        if now - last_time < self._dedup_seconds:
            logger.debug("[Browser] 去重跳过: %s (%.1fs 内已打开)", url, self._dedup_seconds)
            return False

        # 清理过期记录（避免内存泄漏）
        self._cleanup_recent(now)

        try:
            opened = self._open_with_system(url)
            if opened:
                self._recent_urls[url] = now
                logger.info("[Browser] 已打开: %s", url)
            return opened
        except Exception as e:
            logger.warning("[Browser] 打开失败: %s — %s", url, e)
            return False

    def _open_with_system(self, url: str) -> bool:
        """使用系统命令打开浏览器"""
        if self._system == "Darwin":
            cmd = ["open", url]
        elif self._system == "Linux":
            cmd = ["xdg-open", url]
        else:
            logger.warning("[Browser] 不支持的操作系统: %s", self._system)
            return False

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def _open_with_playwright(self, url: str) -> bool:
        """预留 Playwright 接口（未实现）"""
        raise NotImplementedError("Playwright 浏览器支持尚未实现")

    def _cleanup_recent(self, now: float) -> None:
        """清理过期的去重记录"""
        expired = [u for u, t in self._recent_urls.items() if now - t > self._dedup_seconds * 2]
        for u in expired:
            del self._recent_urls[u]


def init_browser_service(config: dict) -> BrowserService:
    """初始化全局 BrowserService 单例"""
    global _instance
    _instance = BrowserService(config)
    return _instance


def get_browser_service() -> "BrowserService | None":
    """获取 BrowserService 单例，未初始化返回 None"""
    return _instance
