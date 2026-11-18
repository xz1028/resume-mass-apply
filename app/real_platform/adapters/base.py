"""真实平台适配器公共骨架：SPI 四方法命令封装、必填六要素校验、幂等复核模式。

适配器仅经注册表被上层调用，无任何自主批量投递行为；
异常严格归类三类统一异常。
"""

import asyncio
from datetime import datetime, timedelta

from app.infra.logging import get_logger
from app.platforms.spi import (
    ApplyResult,
    EncryptedResumeRef,
    PlatformAdapter,
    PlatformRecordRef,
    PlatformUnavailableError,
    PositionDTO,
    RateLimitPolicy,
    StatusReceipt,
)
from app.real_platform.browser.session_manager import get_session_manager
from app.real_platform.browser.worker import BrowserCommand, OpType

logger = get_logger("real_adapter")

REQUIRED_FIELDS = ("position_id", "platform_id", "title", "company", "city", "publish_expire_at")


class RealPlatformAdapterBase:
    """三平台适配器公共骨架：命令封装→worker 提交→deadline→结果校验。"""

    platform_id: str
    rate_limit: RateLimitPolicy
    pages: object  # 对应 app/real_platform/pages/*.py 常量模块

    def __init__(self, pages_module, rate_per_hour: float) -> None:
        self.pages = pages_module
        self.platform_id = pages_module.PLATFORM_ID
        self.rate_limit = RateLimitPolicy(max_per_hour=rate_per_hour)
        self._session_manager = get_session_manager()

    # ---- SPI 契约实现 ----

    def fetch_positions(self, intent, since: datetime) -> list[PositionDTO]:
        from app.real_platform.browser import captcha as captcha_gate

        captcha_gate.gate_check(self._session_factory(), self.platform_id, "fetch")
        command = BrowserCommand(
            op_type=OpType.FETCH,
            payload={
                "intent": intent,
                "search_url": self.pages.build_search_url(
                    keyword=self._intent_keyword(intent), city=intent.city or "北京"
                ),
            },
        )
        raw_list = self._dispatch(command)
        return self._validate_positions(raw_list or [])

    def submit_application(self, position, resume_file: EncryptedResumeRef, contact, greeting: str | None = None) -> ApplyResult:
        from app.real_platform.browser import captcha as captcha_gate

        captcha_gate.gate_check(self._session_factory(), self.platform_id, "delivery")
        payload = {
            "position": position,
            "resume_file": resume_file,
            "contact": contact,
            "apply_flow": self._apply_flow_name(),
        }
        if greeting is not None:
            payload["greeting"] = greeting
        command = BrowserCommand(
            op_type=OpType.SUBMIT,
            payload=payload,
        )
        return self._dispatch(command)

    def fetch_application_status(self, record_refs: list[PlatformRecordRef]) -> list[StatusReceipt]:
        command = BrowserCommand(
            op_type=OpType.STATUS,
            payload={
                "record_refs": record_refs,
                "status_url": self._status_page_url(),
                "status_map": self.pages.STATUS_LABEL_MAP,
            },
        )
        return self._dispatch(command) or []

    def validate_authorization(self, credential: str) -> str:
        from app.real_platform.browser.state_store import credential_to_storage_state

        try:
            storage_state = credential_to_storage_state(credential)
        except Exception:  # noqa: BLE001
            return "unauthorized"
        command = BrowserCommand(
            op_type=OpType.VALIDATE,
            payload={"storage_state": storage_state, "probe_url": self._probe_url()},
        )
        return self._dispatch(command)

    # ---- 子类钩子 ----

    def _apply_flow_name(self) -> str:
        raise NotImplementedError

    def _status_page_url(self) -> str:
        raise NotImplementedError

    def _probe_url(self) -> str:
        return self.pages.LOGIN_URL

    def _intent_keyword(self, intent) -> str:
        keyword = getattr(intent, "industry", None)
        return keyword if keyword else "开发"

    # ---- 公共工具 ----

    def _dispatch(self, command: BrowserCommand):
        """命令提交至平台专属 worker（调用方已在 to_thread 线程）。"""
        worker = self._session_manager.worker_for(self.platform_id)
        worker.bind_executor(self._page_executor)
        worker.start()
        return worker.submit(command)

    def _page_executor(self, page, command):
        """页面操作承载（由绑定模块适配执行：默认经平台执行器模块）。"""
        from app.real_platform.adapters import page_exec

        return page_exec.execute(self, page, command)

    def _validate_positions(self, raw_list: list) -> list[PositionDTO]:
        """必填六要素校验：缺失丢弃并记录结构化日志，不影响同批次。"""
        valid: list[PositionDTO] = []
        dropped = 0
        for raw in raw_list:
            missing = [f for f in REQUIRED_FIELDS if not (raw and raw.get(f))]
            if missing:
                dropped += 1
                logger.warning(
                    "position_dropped",
                    platform_id=self.platform_id,
                    missing_fields=",".join(missing),
                    title=(raw or {}).get("title", "")[:30],
                )
                continue

            valid.append(PositionDTO(**raw))
        if dropped:
            logger.info("fetch_validated", platform_id=self.platform_id, valid=len(valid), dropped=dropped)
        return valid

    @staticmethod
    def _session_factory():
        from app.infra.database import get_database

        return get_database().session

    @staticmethod
    def derive_expire(days: int = 30) -> datetime:
        return datetime.now() + timedelta(days=days)