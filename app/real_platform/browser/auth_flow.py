"""浏览器登录授权流程：空白目录打开登录页→用户自主登录→登录态特征判定→
提取 storage_state→真实校验→凭证经既有授权服务加密落库。

合规红线：worker 不读取/不截获任何表单内容（账密不落盘、不进日志、不进内存快照）。
"""

import time
import uuid

from app.config import settings
from app.infra.logging import get_logger
from app.platforms.spi import PlatformAuthExpiredError, PlatformUnavailableError

logger = get_logger("auth_flow")

LOGIN_POLL_INTERVAL_SECONDS = 2
AUTH_SESSION_TOTAL_TIMEOUT = 600


class BrowserAuthSession:
    """浏览器授权会话（进程内存态，重启自然失效）：十态状态机 + 10 分钟总时限。"""

    def __init__(self, platform_id: str) -> None:
        self.session_id = uuid.uuid4().hex
        self.platform_id = platform_id
        self.status = "created"
        self.failure_reason: str | None = None
        self.created_at = time.monotonic()
        self.remaining_seconds = AUTH_SESSION_TOTAL_TIMEOUT

    def is_terminal(self) -> bool:
        return self.status in ("success", "failed", "expired", "cancelled")

    def elapsed_expired(self) -> bool:
        return time.monotonic() - self.created_at > AUTH_SESSION_TOTAL_TIMEOUT

    def refresh_remaining(self) -> int:
        self.remaining_seconds = max(
            0, int(AUTH_SESSION_TOTAL_TIMEOUT - (time.monotonic() - self.created_at))
        )
        return self.remaining_seconds

    def mark(self, status: str, reason: str | None = None) -> None:
        self.status = status
        if reason is not None:
            self.failure_reason = reason
        logger.info(
            "auth_session_status",
            platform_id=self.platform_id,
            session_id=self.session_id,
            status=status,
            reason=reason or "",
        )


_active_sessions: dict[str, BrowserAuthSession] = {}
_sessions_lock = __import__("threading").Lock()


def create_session(platform_id: str) -> BrowserAuthSession:
    with _sessions_lock:
        for session in _active_sessions.values():
            if session.platform_id == platform_id and not session.is_terminal() and not session.elapsed_expired():
                from app.api.v1.errors import AuthSessionConflictError

                raise AuthSessionConflictError("该平台已有进行中的授权会话")
        session = BrowserAuthSession(platform_id)
        _active_sessions[session.session_id] = session
        return session


def get_session(session_id: str) -> BrowserAuthSession | None:
    with _sessions_lock:
        return _active_sessions.get(session_id)


def cancel_session(session_id: str) -> bool:
    with _sessions_lock:
        session = _active_sessions.get(session_id)
        if session is None:
            return False
        if not session.is_terminal():
            session.mark("cancelled")
        return True


def run_auth_flow(session: BrowserAuthSession, executor, session_factory) -> str | None:
    """执行登录授权主流程，返回加密落库结果（成功）或抛异常（失败）。

    executor(login_page_open_fn, login_detected_fn) 由接入治理层注入：
    - login_page_open_fn(page)：打开平台登录页
    - login_detected_fn(page)：登录态特征元素判定
    流程内完成 storage_state 提取与真实校验（个人页探活）。
    """
    from app.real_platform.browser.worker import BrowserCommand, OpType

    session.mark("browser_opening")
    command = BrowserCommand(op_type=OpType.AUTH_FLOW, payload={"blank_profile": True})
    credential: str | None = None
    try:
        state = executor(command, session)
        session.mark("validating")
        if state is None:
            session.mark("failed", "凭证无效，请重新授权")
            raise PlatformAuthExpiredError("登录态提取失败，请重新授权")
        credential = state
        session.mark("success")
        return credential
    except PlatformAuthExpiredError as exc:
        session.mark("failed", "凭证无效，请重新授权")
        raise PlatformAuthExpiredError(f"登录授权失败：{exc}") from exc
    except PlatformUnavailableError as exc:
        session.mark("failed", "平台暂时无法完成授权校验，请稍后重试")
        raise
    except Exception as exc:  # noqa: BLE001
        session.mark("failed", "平台暂时无法完成授权校验，请稍后重试")
        raise PlatformUnavailableError(f"授权流程异常：{exc}") from exc
    finally:
        if credential is None:
            session.mark("failed", "凭证无效，请重新授权") if session.status != "success" else None