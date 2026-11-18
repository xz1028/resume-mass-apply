"""投递频率控制：按平台独立配置的进程内令牌桶限流。

对限流 30 次/小时的平台，实际投递速率自动控制在平台限制以内。
"""

import threading
import time


class TokenBucket:
    """小容量令牌桶：容量默认 1，匀速补充，保证任意 1 小时窗口内发出次数不超过 max_per_hour。"""

    def __init__(self, max_per_hour: float, burst: float = 1.0) -> None:
        self.max_per_hour = float(max_per_hour)
        self.refill_per_second = self.max_per_hour / 3600.0
        self.capacity = max(burst, 1.0)
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
            self._last_refill = now

    def wait_time(self) -> float:
        """获取一个令牌；返回 0 表示立即获得，正数表示需等待的秒数。"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            deficit = 1.0 - self._tokens
            return deficit / self.refill_per_second

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class RateLimiterRegistry:
    DEFAULT_RATE_PER_HOUR = 30.0

    def __init__(self, policies: dict[str, float] | None = None) -> None:
        self._buckets: dict[str, TokenBucket] = {
            pid: TokenBucket(rate) for pid, rate in (policies or {}).items()
        }

    def wait_time(self, platform_id: str) -> float:
        bucket = self._buckets.get(platform_id)
        if bucket is None:
            bucket = TokenBucket(self.DEFAULT_RATE_PER_HOUR)
            self._buckets[platform_id] = bucket
        return bucket.wait_time()

    def set_policy(self, platform_id: str, max_per_hour: float) -> None:
        self._buckets[platform_id] = TokenBucket(max_per_hour)


_rate_limiters: RateLimiterRegistry | None = None


def get_rate_limiters() -> RateLimiterRegistry:
    global _rate_limiters
    if _rate_limiters is None:
        from app.config import settings

        _rate_limiters = RateLimiterRegistry(settings.platform_rate_limits_per_hour)
    return _rate_limiters


def reset_rate_limiter_singleton() -> None:
    global _rate_limiters
    _rate_limiters = None