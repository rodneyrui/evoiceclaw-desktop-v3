"""空闲监控器 — 检测系统是否空闲以触发评测

检测条件：
- CPU 使用率 < 20% 持续 5 分钟
- 内存使用率 < 80%
- 无用户活动（无 HTTP 请求）持续 5 分钟
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("[IdleMonitor] psutil 未安装，空闲检测功能受限")

logger = logging.getLogger("evoiceclaw.evaluation.idle_monitor")


class IdleMonitor:
    """系统空闲监控器"""

    def __init__(
        self,
        cpu_threshold: float = 20.0,
        memory_threshold: float = 80.0,
        idle_duration: int = 300,  # 5 分钟
        check_interval: int = 60,  # 每分钟检查一次
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.idle_duration = idle_duration
        self.check_interval = check_interval

        self._last_activity_time: Optional[datetime] = None
        self._idle_start_time: Optional[datetime] = None
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

    def record_activity(self) -> None:
        """记录用户活动（由 HTTP 中间件调用）"""
        self._last_activity_time = datetime.now()
        # 如果之前处于空闲状态，重置空闲开始时间
        if self._idle_start_time is not None:
            logger.debug("[IdleMonitor] 检测到用户活动，重置空闲状态")
            self._idle_start_time = None

    def _check_cpu_idle(self) -> bool:
        """检查 CPU 是否空闲"""
        if not PSUTIL_AVAILABLE:
            return True  # 无法检测，假设空闲

        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            return cpu_percent < self.cpu_threshold
        except Exception as e:
            logger.warning(f"[IdleMonitor] CPU 检测失败: {e}")
            return True

    def _check_memory_idle(self) -> bool:
        """检查内存是否充足"""
        if not PSUTIL_AVAILABLE:
            return True

        try:
            memory = psutil.virtual_memory()
            return memory.percent < self.memory_threshold
        except Exception as e:
            logger.warning(f"[IdleMonitor] 内存检测失败: {e}")
            return True

    def _check_user_idle(self) -> bool:
        """检查用户是否无活动"""
        if self._last_activity_time is None:
            # 首次启动，假设无活动
            return True

        elapsed = (datetime.now() - self._last_activity_time).total_seconds()
        return elapsed >= self.idle_duration

    def is_idle(self) -> bool:
        """检查系统是否空闲"""
        cpu_idle = self._check_cpu_idle()
        memory_idle = self._check_memory_idle()
        user_idle = self._check_user_idle()

        all_idle = cpu_idle and memory_idle and user_idle

        if all_idle:
            if self._idle_start_time is None:
                self._idle_start_time = datetime.now()
                logger.info("[IdleMonitor] 系统进入空闲状态")
            else:
                # 检查是否持续空闲足够长时间
                idle_elapsed = (datetime.now() - self._idle_start_time).total_seconds()
                if idle_elapsed >= self.idle_duration:
                    return True
        else:
            if self._idle_start_time is not None:
                logger.debug(f"[IdleMonitor] 系统退出空闲状态 (CPU={cpu_idle}, MEM={memory_idle}, USER={user_idle})")
                self._idle_start_time = None

        return False

    async def _monitor_loop(self) -> None:
        """监控循环"""
        logger.info(f"[IdleMonitor] 启动监控 (CPU<{self.cpu_threshold}%, MEM<{self.memory_threshold}%, 持续{self.idle_duration}s)")

        while self._is_running:
            try:
                if self.is_idle():
                    logger.info("[IdleMonitor] 系统空闲，可触发评测")
                    # 这里可以发送事件通知调度器
                    # 暂时只记录日志

                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[IdleMonitor] 监控循环异常: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)

    def start(self) -> None:
        """启动监控"""
        if self._is_running:
            logger.warning("[IdleMonitor] 监控已在运行")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("[IdleMonitor] 监控已启动")

    async def stop(self) -> None:
        """停止监控"""
        if not self._is_running:
            return

        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[IdleMonitor] 监控已停止")


# ── 全局单例 ──
_monitor_instance: Optional[IdleMonitor] = None


def get_idle_monitor() -> IdleMonitor:
    """获取全局 IdleMonitor 单例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = IdleMonitor()
    return _monitor_instance
