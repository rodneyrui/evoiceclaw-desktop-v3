"""Provider 运行时健康追踪

在 model_matrix.py 的静态评分之上叠加动态健康感知，
实现自动降级和故障恢复。

R5 增强: 指数退避添加 jitter（随机抖动），避免雷鸣群效应。

线程安全: 所有方法通过 threading.Lock 保护。
"""

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("evoiceclaw.kernel.provider_health")

# 默认参数
_DEFAULT_PARAMS = {
    "cooldown_base": 60,      # 基础冷却时间（秒）
    "cooldown_max": 600,       # 最大冷却时间（秒）
    "min_multiplier": 0.3,     # 最低健康系数
    "recovery_window": 120,    # 恢复窗口（秒）
    "jitter_factor": 0.25,     # R5: jitter 因子（冷却时间的 ±25%）
}


def _apply_jitter(value: float, factor: float) -> float:
    """R5: 为退避时间添加随机 jitter

    Args:
        value: 原始退避时间
        factor: jitter 因子（0.25 = ±25%）

    Returns:
        添加 jitter 后的退避时间
    """
    jitter_range = value * factor
    return value + random.uniform(-jitter_range, jitter_range)


@dataclass
class ProviderStats:
    """单个 Provider 的运行时统计"""

    recent_results: deque = field(default_factory=lambda: deque(maxlen=50))
    recent_latencies: deque = field(default_factory=lambda: deque(maxlen=50))
    last_failure_at: float = 0.0
    consecutive_failures: int = 0
    is_rate_limited: bool = False
    rate_limit_until: float = 0.0

    @property
    def success_rate(self) -> float:
        """最近 50 次请求的成功率"""
        if not self.recent_results:
            return 1.0  # 无数据时假设健康
        return sum(1 for r in self.recent_results if r) / len(self.recent_results)

    @property
    def avg_latency_ms(self) -> float:
        """最近请求的平均延迟（毫秒）"""
        if not self.recent_latencies:
            return 0.0
        return sum(self.recent_latencies) / len(self.recent_latencies)

    def compute_health_multiplier(self, params: dict) -> float:
        """健康系数，用于乘以静态评分

        Args:
            params: 健康参数字典

        - rate_limited 且在冷却期 → 0.0（完全屏蔽）
        - consecutive_failures >= 3 → 指数退避冷却 + 线性渐进恢复
        - 否则 → max(min_multiplier, success_rate)
        """
        now = time.monotonic()
        cooldown_base = params.get("cooldown_base", 60)
        cooldown_max = params.get("cooldown_max", 600)
        min_multiplier = params.get("min_multiplier", 0.3)
        recovery_window = params.get("recovery_window", 120)

        # 限速冷却期内完全屏蔽
        if self.is_rate_limited and now < self.rate_limit_until:
            return 0.0

        # 限速冷却期已过，自动恢复
        if self.is_rate_limited and now >= self.rate_limit_until:
            self.is_rate_limited = False

        # 连续失败 >= 3 次: 指数退避冷却 + 渐进恢复
        if self.consecutive_failures >= 3:
            cooldown = min(cooldown_base * (2 ** (self.consecutive_failures - 3)), cooldown_max)
            cooldown_end = self.last_failure_at + cooldown

            if now < cooldown_end:
                return 0.1

            # 冷却期已过: recovery_window 内线性恢复
            elapsed_since_cooldown = now - cooldown_end
            recovery_factor = min(1.0, elapsed_since_cooldown / recovery_window)
            base = max(min_multiplier, self.success_rate)
            return 0.1 + (base - 0.1) * recovery_factor

        return max(min_multiplier, self.success_rate)


class ProviderHealthTracker:
    """全局 Provider 健康追踪器"""

    def __init__(self) -> None:
        self._stats: dict[str, ProviderStats] = {}
        self._lock = threading.Lock()
        self._health_params: dict[str, dict] = {}

    def load_config(self, config: dict) -> None:
        """从应用配置加载 per-provider 健康监控参数

        Args:
            config: 应用配置字典，读取 health_monitoring.provider_config
        """
        health_cfg = config.get("health_monitoring", {})
        self._health_params = health_cfg.get("provider_config", {})
        if self._health_params:
            logger.info(
                "[HealthTracker] 加载健康配置: %d 个 Provider",
                len(self._health_params),
            )

    def _get_provider_params(self, provider: str) -> dict:
        """获取 Provider 的监控参数（优先自定义配置，兜底默认值）"""
        return self._health_params.get(provider, _DEFAULT_PARAMS)

    def _get_stats(self, provider: str) -> ProviderStats:
        """获取或创建 Provider 的统计对象（调用方须持有锁）"""
        if provider not in self._stats:
            self._stats[provider] = ProviderStats()
        return self._stats[provider]

    def record_success(self, provider: str, latency_ms: float) -> None:
        """记录一次成功请求"""
        with self._lock:
            stats = self._get_stats(provider)
            stats.recent_results.append(True)
            stats.recent_latencies.append(latency_ms)
            stats.consecutive_failures = 0

    def record_failure(self, provider: str, *, is_rate_limit: bool = False) -> None:
        """记录一次失败请求

        Args:
            provider: Provider ID（如 "deepseek"）
            is_rate_limit: 是否为 429 限速错误，触发冷却机制
        """
        with self._lock:
            stats = self._get_stats(provider)
            stats.recent_results.append(False)
            stats.last_failure_at = time.monotonic()
            stats.consecutive_failures += 1

            if is_rate_limit:
                params = self._get_provider_params(provider)
                cooldown_base = params.get("cooldown_base", 60)
                cooldown_max = params.get("cooldown_max", 600)
                jitter_factor = params.get("jitter_factor", 0.25)
                stats.is_rate_limited = True
                # R5: 指数退避 + jitter
                raw_cooldown = min(
                    cooldown_base * (2 ** max(0, stats.consecutive_failures - 1)),
                    cooldown_max,
                )
                cooldown = _apply_jitter(raw_cooldown, jitter_factor)
                stats.rate_limit_until = time.monotonic() + cooldown
                logger.info(
                    "[HealthTracker] %s 限速，冷却 %.1fs（含 jitter）",
                    provider, cooldown,
                )

    def health_multiplier(self, provider: str) -> float:
        """获取 Provider 的健康系数（0.0 ~ 1.0）"""
        with self._lock:
            stats = self._stats.get(provider)
            if not stats:
                return 1.0  # 无记录，假设健康
            params = self._get_provider_params(provider)
            return stats.compute_health_multiplier(params)

    def get_status(self) -> dict:
        """返回所有 Provider 的健康状态（用于 API 端点）"""
        with self._lock:
            now = time.monotonic()
            result = {}
            for provider, stats in self._stats.items():
                params = self._get_provider_params(provider)
                cooldown_base = params.get("cooldown_base", 60)
                cooldown_max = params.get("cooldown_max", 600)

                # 计算剩余冷却时间
                cooldown_remaining = 0.0
                if stats.consecutive_failures >= 3:
                    cooldown = min(
                        cooldown_base * (2 ** (stats.consecutive_failures - 3)),
                        cooldown_max,
                    )
                    cooldown_end = stats.last_failure_at + cooldown
                    if now < cooldown_end:
                        cooldown_remaining = round(cooldown_end - now, 1)

                result[provider] = {
                    "health": round(stats.compute_health_multiplier(params), 2),
                    "success_rate": round(stats.success_rate, 2),
                    "avg_latency_ms": round(stats.avg_latency_ms, 1),
                    "consecutive_failures": stats.consecutive_failures,
                    "is_rate_limited": stats.is_rate_limited,
                    "total_requests": len(stats.recent_results),
                    "cooldown_remaining": cooldown_remaining,
                }
            return result


# ── 全局单例 ──

_tracker: ProviderHealthTracker | None = None


def init_health_tracker() -> ProviderHealthTracker:
    """在 lifespan 中调用，初始化全局单例"""
    global _tracker
    _tracker = ProviderHealthTracker()
    return _tracker


def get_health_tracker() -> ProviderHealthTracker:
    """获取全局单例（lifespan 中已初始化）"""
    if _tracker is None:
        raise RuntimeError("ProviderHealthTracker 未初始化，请确认 lifespan 已执行")
    return _tracker
