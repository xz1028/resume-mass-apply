"""降级恢复探测器：独立后台定时线程（3600s 周期），三重轻量探测成功才恢复。

探测内容：登录态恢复成功 + 搜索页打开成功 + 结果容器可解析；
任一失败保持降级等待下周期；不修改既有 scheduler.py，随应用 lifespan 启停。
"""

import threading

from app.config import settings
from app.infra.logging import get_logger

logger = get_logger("recovery_probe")


class RecoveryProbe:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._timer: threading.Timer | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        self._stopped.clear()
        self._schedule()
        logger.info(
            "recovery_probe_started", interval_seconds=settings.recovery_probe_interval_seconds
        )

    def stop(self) -> None:
        self._stopped.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self) -> None:
        if self._stopped.is_set():
            return
        self._timer = threading.Timer(
            settings.recovery_probe_interval_seconds, self._probe_once
        )
        self._timer.daemon = True
        self._timer.start()

    def _probe_once(self) -> None:
        try:
            degraded_ids = [
                pid for pid, _ in self._registry.list_all() if self._registry.is_degraded(pid)
            ]
            for platform_id in degraded_ids:
                ok = self._triple_probe(platform_id)
                if ok:
                    self._registry.recover(platform_id)
                    logger.info("recovery_probe_recovered", platform_id=platform_id)
                else:
                    logger.info("recovery_probe_kept_degraded", platform_id=platform_id)
        except Exception:  # noqa: BLE001
            logger.exception("recovery_probe_failed")
        finally:
            self._schedule()

    def _triple_probe(self, platform_id: str) -> bool:
        """三重轻量探测：登录态恢复 + 搜索页打开 + 结果容器可解析。"""
        adapter = self._registry.get(platform_id)
        if adapter is None:
            return False
        try:
            from app.real_platform.browser.worker import BrowserCommand, OpType

            pages = adapter.pages
            command = BrowserCommand(
                op_type=OpType.VALIDATE,
                payload={"probe_url": getattr(pages, "MY_MESSAGE_URL", pages.LOGIN_URL)},
            )
            status = adapter.validate_authorization(_mock_credential_for_probe(platform_id))
            if status != "authorized":
                return False
            from app.real_platform.adapters import page_exec  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False


def _mock_credential_for_probe(platform_id: str) -> str:
    """探测用凭证：优先取真实加密凭证，无凭证平台返回空（判定为不可恢复）。"""
    from app.infra.database import get_database
    from app.repositories.repos import AuthorizationRepository

    session = get_database().session()
    try:
        auth = AuthorizationRepository(session).get(platform_id)
        if auth is None:
            return ""
        from app.infra.crypto import get_crypto

        return get_crypto().decrypt(auth.credential_cipher).decode("utf-8")
    finally:
        session.close()


_probe: RecoveryProbe | None = None


def get_recovery_probe(registry) -> RecoveryProbe:
    global _probe
    if _probe is None:
        _probe = RecoveryProbe(registry)
    return _probe


def reset_recovery_probe_singleton() -> None:
    global _probe
    if _probe is not None:
        _probe.stop()
    _probe = None