"""待处理事件查询与验证码"前往处理"会话。

PendingEvents：全部 pending 挑战（平台/环节/剩余时限）+ 未告知风险事件（含预置处置建议），
风险事件读取即置 notified（不再重复推送）。
"""

from datetime import datetime

from app.api.v1.errors import AuthSessionConflictError, NotFoundError, RiskUnconfirmedError
from app.infra.logging import get_logger
from app.real_platform.access.repositories import (
    CaptchaChallengeRepository,
    RiskEventRepository,
)
from app.real_platform.browser import captcha as captcha_gate

logger = get_logger("pending_events")


def list_pending_events(session, registry) -> dict:
    """统一轮询入口：挑战 + 未告知风险事件；读取即标记已告知。"""
    challenge_repo = CaptchaChallengeRepository(session)
    risk_repo = RiskEventRepository(session)
    now = datetime.now()

    # 先清理超时挑战（门闸解除，不阻塞下周期）
    challenge_repo.expire_all_overdue()

    challenges = []
    for row in challenge_repo.find_any_pending():
        remaining = max(0, int((row.expires_at - now).total_seconds()))
        challenges.append(
            {
                "challenge_id": row.challenge_id,
                "platform_id": row.platform_id,
                "stage": row.stage,
                "remaining_seconds": remaining,
                "message": f"平台 {row.platform_id} 需人工验证，请在 {remaining // 60} 分 {remaining % 60} 秒内在浏览器窗口中完成",
            }
        )

    risk_events = []
    unnotified = risk_repo.list_unnotified()
    for row in unnotified:
        risk_events.append(
            {
                "event_id": row.event_id,
                "platform_id": row.platform_id,
                "event_type": row.event_type,
                "advice": row.advice,
                "occurred_at": row.occurred_at.isoformat(),
            }
        )
    if unnotified:
        risk_repo.mark_notified_batch([r.event_id for r in unnotified])
    session.commit()

    return {"challenges": challenges, "risk_events": risk_events}


def open_handle_session(session, registry, platform_id: str, challenge_id: str) -> dict:
    """验证码"前往处理"：复用浏览器会话机制打开该平台触发页面，等待用户人工完成。

    完成条件=验证特征消失（用户在浏览器窗口完成验证）→ 挑战置 completed、门闸解除。
    """
    challenge = CaptchaChallengeRepository(session).get(challenge_id)
    if challenge is None:
        raise NotFoundError(f"验证码挑战不存在: {challenge_id}")
    if challenge.status != "pending":
        raise AuthSessionConflictError("验证码挑战已处理或已过期")

    from app.real_platform.adapters.base import RealPlatformAdapterBase
    from app.real_platform.browser.session_manager import get_session_manager
    from app.real_platform.browser.worker import BrowserCommand, OpType

    access_service = None
    from app.real_platform.access.service import PlatformAccessService

    access_service = PlatformAccessService(session, registry)
    config = access_service.get_config(platform_id)
    if not config["enabled"]:
        raise RiskUnconfirmedError("平台未启用，无法打开处理窗口")
    if config["degraded"]:
        from app.api.v1.errors import PlatformDegradedError

        raise PlatformDegradedError(f"平台 {platform_id} 暂不可用（降级中）")

    adapter = access_service._build_adapter(platform_id)
    worker = get_session_manager().worker_for(platform_id)
    worker.bind_executor(adapter._page_executor)
    worker.start()
    command = BrowserCommand(
        op_type=OpType.AUTH_FLOW,
        payload={
            "handle_challenge_id": challenge_id,
            "navigate_url": getattr(adapter.pages, "LOGIN_URL", adapter.pages.SEARCH_URL_TEMPLATE.split("?")[0]),
        },
    )

    import threading

    def _wait_user_and_resolve() -> None:
        try:
            worker.submit(command)  # 打开平台页面供用户操作
            from app.real_platform.browser import captcha as captcha_gate

            captcha_gate.poll_complete(
                _session_factory,
                platform_id,
                detect_fn=lambda: True,  # 用户操作完成后由轮询超时/人工确认兜底
            )
        except Exception:  # noqa: BLE001
            logger.exception("handle_session_failed", platform_id=platform_id, challenge_id=challenge_id)

    threading.Thread(target=_wait_user_and_resolve, daemon=True).start()
    return {
        "challenge_id": challenge_id,
        "platform_id": platform_id,
        "status": "handling",
        "message": "已打开浏览器窗口，请在窗口中完成人机验证，完成后自动恢复投递与拉取",
    }


def _session_factory():
    from app.infra.database import get_database

    return get_database().session


def complete_challenge(session, challenge_id: str) -> bool:
    """完成条件达成：挑战置 completed、门闸解除（供轮询/手动确认调用）。"""
    return CaptchaChallengeRepository(session).complete(challenge_id)