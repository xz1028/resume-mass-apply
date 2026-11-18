"""验证码挑战门闸：检测→pending 落库→人工等待→完成后解除。

合规红线：全程无任何自动识别/破解/第三方打码行为（spec 5.6.1.2）。
门闸：该平台存在 pending 挑战期间一切自动化命令快速失败（不进页面、不等待）。
"""

from datetime import datetime

from app.config import settings
from app.infra.logging import get_logger
from app.infra.metrics import inc_captcha_challenge
from app.platforms.spi import PlatformRateLimitedError
from app.real_platform.access.repositories import CaptchaChallengeRepository

logger = get_logger("captcha_gate")


def gate_check(session_factory, platform_id: str, stage: str) -> None:
    """命令执行前门闸检查：存在 pending 挑战 → 1 秒内快速失败。"""
    session = session_factory()
    try:
        challenge = CaptchaChallengeRepository(session).find_pending(platform_id)
        if challenge is not None:
            remaining = max(0, int((challenge.expires_at - datetime.now()).total_seconds()))
            raise PlatformRateLimitedError(
                f"平台 {platform_id} 需人工验证（剩余 {remaining // 60} 分 {remaining % 60} 秒），"
                "请在浏览器窗口中完成后再试"
            )
    finally:
        session.close()


def open_challenge(session_factory, platform_id: str, stage: str) -> str:
    """检测到验证码特征：创建 pending 挑战（指标计数 + 落库），返回挑战 ID。"""
    session = session_factory()
    try:
        repo = CaptchaChallengeRepository(session)
        existing = repo.find_pending(platform_id)
        if existing is not None:
            return existing.challenge_id
        challenge = repo.create(
            platform_id=platform_id,
            stage=stage,
            timeout_seconds=settings.captcha_wait_timeout_seconds,
        )
        session.commit()
        inc_captcha_challenge(platform_id=platform_id, stage=stage)
        logger.warning(
            "captcha_challenge_opened",
            platform_id=platform_id,
            stage=stage,
            challenge_id=challenge.challenge_id,
            timeout=settings.captcha_wait_timeout_seconds,
        )
        return challenge.challenge_id
    finally:
        session.close()


def poll_complete(session_factory, platform_id: str, detect_fn) -> bool:
    """轮询检测验证特征是否消失（用户在浏览器窗口人工完成）。"""
    session = session_factory()
    try:
        repo = CaptchaChallengeRepository(session)
        challenge = repo.find_pending(platform_id)
        if challenge is None:
            return True
        repo.expire_all_overdue(platform_id)
        session.commit()
        challenge = repo.find_pending(platform_id)
        if challenge is None:
            return True
        session.close()
        if detect_fn():
            session = session_factory()
            try:
                CaptchaChallengeRepository(session).complete(challenge.challenge_id)
                session.commit()
                logger.info(
                    "captcha_challenge_completed",
                    platform_id=platform_id,
                    challenge_id=challenge.challenge_id,
                )
                return True
            finally:
                session.close()
        return False
    finally:
        session.close()


def expire_overdue(session_factory, platform_id: str | None = None) -> int:
    """超时挑战置 expired：门闸解除，不阻塞下一拉取周期。"""
    session = session_factory()
    try:
        count = CaptchaChallengeRepository(session).expire_all_overdue(platform_id)
        session.commit()
        if count:
            logger.info("captcha_challenges_expired", platform_id=platform_id or "all", count=count)
        return count
    finally:
        session.close()