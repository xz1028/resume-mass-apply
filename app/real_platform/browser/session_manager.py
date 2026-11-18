"""浏览器会话管理器：每平台至多 1 个受控实例；空闲回收；禁用/撤销联动终止；凭证巡检兜底。"""

import threading
from collections.abc import Callable

from app.config import settings
from app.infra.logging import get_logger
from app.real_platform.browser import state_store
from app.real_platform.browser.worker import PlatformBrowserWorker

logger = get_logger("session_manager")


class BrowserSessionManager:
    """平台 → worker（含浏览器实例）一对一映射。"""

    def __init__(self) -> None:
        self._workers: dict[str, PlatformBrowserWorker] = {}
        self._lock = threading.Lock()
        self._patrol_timer: threading.Timer | None = None
        self._credential_probe: Callable[[str], bool] | None = None

    def bind_credential_probe(self, probe: Callable[[str], bool]) -> None:
        """巡检用：platform_id → 凭证是否仍存在（授权撤销兜底）。"""
        self._credential_probe = probe

    def worker_for(self, platform_id: str) -> PlatformBrowserWorker:
        with self._lock:
            worker = self._workers.get(platform_id)
            if worker is None:
                worker = PlatformBrowserWorker(platform_id)
                self._workers[platform_id] = worker
            return worker

    def terminate(self, platform_id: str, clear_profile: bool = False) -> None:
        """禁用/撤销时立即终止进行中会话（当前命令抛平台不可用异常）。"""
        with self._lock:
            worker = self._workers.pop(platform_id, None)
        if worker is not None:
            worker.stop(close_browser=True)
            logger.info("browser_session_terminated", platform_id=platform_id)
        if clear_profile:
            state_store.clear_profile(platform_id)

    def start_patrol(self) -> None:
        """60s 巡检：平台凭证已被删除时自动关闭会话并清理用户数据目录。"""
        self._schedule_patrol()

    def stop_patrol(self) -> None:
        if self._patrol_timer is not None:
            self._patrol_timer.cancel()
            self._patrol_timer = None

    def _schedule_patrol(self) -> None:
        self._patrol_timer = threading.Timer(
            settings.browser_patrol_interval_seconds, self._patrol_once
        )
        self._patrol_timer.daemon = True
        self._patrol_timer.start()

    def _patrol_once(self) -> None:
        try:
            if self._credential_probe is not None:
                with self._lock:
                    platform_ids = list(self._workers.keys())
                for platform_id in platform_ids:
                    if not self._credential_probe(platform_id):
                        self.terminate(platform_id, clear_profile=True)
                        logger.info(
                            "browser_patrol_revoked",
                            platform_id=platform_id,
                            message="巡检发现凭证已删除，自动关闭会话并清理用户数据目录",
                        )
        except Exception:  # noqa: BLE001
            logger.exception("browser_patrol_failed")
        finally:
            self._schedule_patrol()

    def shutdown(self) -> None:
        self.stop_patrol()
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop(close_browser=True)


_session_manager: BrowserSessionManager | None = None


def get_session_manager() -> BrowserSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = BrowserSessionManager()
    return _session_manager


def reset_session_manager_singleton() -> None:
    global _session_manager
    if _session_manager is not None:
        _session_manager.shutdown()
    _session_manager = None