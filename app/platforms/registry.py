"""适配器注册表与健康状态管理。

连续 3 次调用失败自动标记平台降级（仅提供职位浏览）；
恢复探测成功后自动恢复并触发补拉回调。
"""

from collections.abc import Callable

from app.infra.logging import get_logger
from app.platforms.spi import PlatformAdapter

logger = get_logger("registry")

DEGRADE_FAILURE_THRESHOLD = 3


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}
        self._names: dict[str, str] = {}
        self._degraded: dict[str, str] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._recovery_callbacks: list[Callable[[str], None]] = []

    def register(self, adapter: PlatformAdapter, name: str | None = None) -> None:
        self._adapters[adapter.platform_id] = adapter
        self._names[adapter.platform_id] = name or adapter.platform_id
        self._consecutive_failures.setdefault(adapter.platform_id, 0)
        logger.info("platform_registered", platform_id=adapter.platform_id)

    def get(self, platform_id: str) -> PlatformAdapter | None:
        return self._adapters.get(platform_id)

    def require(self, platform_id: str) -> PlatformAdapter:
        adapter = self._adapters.get(platform_id)
        if adapter is None:
            raise KeyError(f"平台未注册: {platform_id}")
        return adapter

    def list_all(self) -> list[tuple[str, str]]:
        return [(pid, self._names.get(pid, pid)) for pid in self._adapters]

    def list_healthy(self) -> list[PlatformAdapter]:
        return [a for pid, a in self._adapters.items() if pid not in self._degraded]

    def is_degraded(self, platform_id: str) -> bool:
        return platform_id in self._degraded

    def degraded_reason(self, platform_id: str) -> str | None:
        return self._degraded.get(platform_id)

    def mark_degraded(self, platform_id: str, reason: str = "平台接口异常") -> None:
        self._degraded[platform_id] = reason
        logger.warning("platform_degraded", platform_id=platform_id, reason=reason)

    def recover(self, platform_id: str) -> None:
        was_degraded = platform_id in self._degraded
        self._degraded.pop(platform_id, None)
        self._consecutive_failures[platform_id] = 0
        if was_degraded:
            logger.info("platform_recovered", platform_id=platform_id)
            for callback in self._recovery_callbacks:
                try:
                    callback(platform_id)
                except Exception:  # noqa: BLE001
                    logger.exception("recovery_callback_failed", platform_id=platform_id)

    def record_call_failure(self, platform_id: str) -> None:
        count = self._consecutive_failures.get(platform_id, 0) + 1
        self._consecutive_failures[platform_id] = count
        if count >= DEGRADE_FAILURE_THRESHOLD and platform_id not in self._degraded:
            self.mark_degraded(platform_id, reason=f"连续 {count} 次调用失败")

    def record_call_success(self, platform_id: str) -> None:
        self._consecutive_failures[platform_id] = 0
        if platform_id in self._degraded:
            self.recover(platform_id)

    def on_recovery(self, callback: Callable[[str], None]) -> None:
        self._recovery_callbacks.append(callback)


_registry: AdapterRegistry | None = None


def get_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


def reset_registry_singleton() -> None:
    global _registry
    _registry = None