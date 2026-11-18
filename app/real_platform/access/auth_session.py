"""浏览器授权会话管理：十态状态机、10 分钟总时限、前置校验、成功/失败/取消路径。

成功路径：提取凭证→真实校验→复用既有 AuthorizationService.authorize 加密落库→触发职位拉取；
失败路径：区分凭证无效/平台不可达，凭证一律不保存；取消路径：关闭浏览器、不保存凭证。
"""

import asyncio

from app.api.v1.errors import (
    AuthSessionConflictError,
    NotFoundError,
    PlatformDegradedError,
    RiskUnconfirmedError,
)
from app.config import DEFAULT_USER_ID
from app.domain.models import AuthStatus
from app.infra.audit import AuditAction, record_audit
from app.infra.logging import get_logger
from app.real_platform.access.service import PlatformAccessService
from app.real_platform.browser import auth_flow as browser_auth_flow

logger = get_logger("auth_session_service")


class BrowserAuthSessionService:
    def __init__(self, session, registry) -> None:
        self._session = session
        self._registry = registry

    # ---------- 会话查询（轮询用） ----------

    def poll(self, session_id: str) -> dict:
        session = browser_auth_flow.get_session(session_id)
        if session is None:
            raise NotFoundError(f"授权会话不存在: {session_id}")
        remaining = session.refresh_remaining()
        if session.elapsed_expired() and not session.is_terminal():
            session.mark("expired", "会话超时（10 分钟）")
        return {
            "session_id": session.session_id,
            "platform_id": session.platform_id,
            "status": session.status,
            "remaining_seconds": remaining,
            "failure_reason": session.failure_reason,
        }

    def cancel(self, session_id: str) -> None:
        if not browser_auth_flow.cancel_session(session_id):
            raise NotFoundError(f"授权会话不存在: {session_id}")
        from app.real_platform.browser.session_manager import get_session_manager

        get_session_manager().terminate(
            next(
                (
                    s.platform_id
                    for s in browser_auth_flow._active_sessions.values()
                    if s.session_id == session_id
                ),
                "",
            )
        )
        logger.info("auth_session_cancelled", session_id=session_id)

    # ---------- 会话创建与执行 ----------

    def create_and_run(self, platform_id: str, user_id: str = DEFAULT_USER_ID) -> dict:
        access = PlatformAccessService(self._session, self._registry)
        config = access.get_config(platform_id)
        if not config["enabled"]:
            raise RiskUnconfirmedError(
                "平台未启用，请先在平台列表中启用该平台后再发起浏览器授权"
            )
        if not config["risk_confirmed"]:
            raise RiskUnconfirmedError("请先阅读并确认平台接入风险告知")
        access.ensure_no_existing_authorization(platform_id)
        if config["degraded"]:
            raise PlatformDegradedError(f"平台 {platform_id} 暂不可用（降级中），请稍后重试")
        session = browser_auth_flow.create_session(platform_id)
        record_audit(
            self._session,
            AuditAction.BROWSER_AUTH_SESSION,
            f"用户 {user_id} 发起平台 {platform_id} 浏览器授权会话 {session.session_id}",
        )
        self._session.commit()
        asyncio.get_event_loop().run_in_executor(
            None, self._run_session, session, user_id
        ) if False else None
        import threading

        threading.Thread(
            target=self._run_session, args=(session, user_id), daemon=True
        ).start()
        return {
            "session_id": session.session_id,
            "platform_id": platform_id,
            "status": session.status,
            "remaining_seconds": session.refresh_remaining(),
        }

    def _run_session(self, session, user_id: str) -> None:
        """后台线程：执行授权主流程（凭证经既有授权服务加密落库）。"""
        try:
            from app.real_platform.adapters.base import RealPlatformAdapterBase
            from app.real_platform.browser.session_manager import get_session_manager
            from app.real_platform.browser.worker import BrowserCommand, OpType

            access = PlatformAccessService(self._session, self._registry)
            adapter = access._build_adapter(session.platform_id)
            worker = get_session_manager().worker_for(session.platform_id)
            worker.bind_executor(adapter._page_executor)
            worker.start()
            command = BrowserCommand(op_type=OpType.AUTH_FLOW, payload={"auth_session": session})
            session.mark("browser_opening")
            credential = worker.submit(command)
            if credential is None:
                session.mark("failed", "凭证无效，请重新授权")
                return
            session.mark("validating")
            # 真实校验 + 加密落库（复用既有授权服务：成功即触发一次职位拉取）
            from app.infra.database import get_database
            from app.services.authorization_service import AuthorizationService

            auth_session_db = get_database().session()
            try:
                auth_service = AuthorizationService(
                    auth_session_db, _get_crypto(), self._registry
                )
                auth_service.authorize(user_id, session.platform_id, credential)
                session.mark("success")
            finally:
                auth_session_db.close()
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)
            if "授权" in reason or "登录" in reason or "AuthExpired" in type(exc).__name__:
                session.mark("failed", "凭证无效，请重新授权")
            else:
                session.mark("failed", "平台暂时无法完成授权校验，请稍后重试")
            logger.warning(
                "auth_session_failed",
                platform_id=session.platform_id,
                session_id=session.session_id,
                reason=reason,
            )
        finally:
            from app.real_platform.browser.session_manager import get_session_manager

            get_session_manager().terminate(session.platform_id)


def _get_crypto():
    from app.infra.crypto import get_crypto

    return get_crypto()