"""平台授权服务：凭证加密管理、撤销联动、授权状态查询。"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v1.errors import (
    NotFoundError,
    PlatformAuthExpiredError as APIPlatformAuthExpiredError,
    PlatformDegradedError,
)
from app.domain.models import AuthStatus, PlatformAuthorization
from app.infra.audit import AuditAction, record_audit
from app.infra.crypto import CryptoService
from app.infra.logging import get_logger
from app.platforms.registry import AdapterRegistry
from app.repositories.repos import AuthorizationRepository

logger = get_logger("authorization_service")


class AuthorizationService:
    def __init__(self, session: Session, crypto: CryptoService, registry: AdapterRegistry) -> None:
        self._session = session
        self._crypto = crypto
        self._registry = registry

    def list_platforms(self) -> list[dict]:
        repo = AuthorizationRepository(self._session)
        platforms = []
        for platform_id, name in self._registry.list_all():
            auth = repo.get(platform_id)
            auth_status = auth.status.value if auth else AuthStatus.unauthorized.value
            platforms.append(
                {
                    "platform_id": platform_id,
                    "name": name,
                    "auth_status": auth_status,
                    "degraded": self._registry.is_degraded(platform_id),
                }
            )
        return platforms

    def authorize(self, user_id: str, platform_id: str, credential: str) -> dict:
        adapter = self._registry.get(platform_id)
        if adapter is None:
            raise NotFoundError(f"平台不存在: {platform_id}")
        if self._registry.is_degraded(platform_id):
            raise PlatformDegradedError(f"平台 {platform_id} 暂不可用（降级中），请稍后重试")
        status = adapter.validate_authorization(credential)
        if status != AuthStatus.authorized:
            raise APIPlatformAuthExpiredError("平台凭证无效，请检查后重新授权")
        cipher = self._crypto.encrypt(credential.encode("utf-8"))
        repo = AuthorizationRepository(self._session)
        repo.upsert(
            PlatformAuthorization(
                platform_id=platform_id,
                user_id=user_id,
                credential_cipher=cipher,
                status=AuthStatus.authorized,
                authorized_at=datetime.now(),
            )
        )
        record_audit(
            self._session,
            AuditAction.AUTHORIZE,
            f"用户 {user_id} 授权平台 {platform_id}",
        )
        self._session.commit()
        logger.info("platform_authorized", platform_id=platform_id, user_id=user_id)
        # 授权成功后立即拉取一次职位，避免用户等待下一个调度周期才能看到岗位
        try:
            from app.services.job_service import JobService

            fetch_result = JobService(self._session, self._registry).fetch_positions(user_id)
            logger.info("post_authorize_fetch", result=fetch_result)
        except Exception:  # noqa: BLE001
            logger.exception("post_authorize_fetch_failed", platform_id=platform_id)
        return {
            "platform_id": platform_id,
            "name": dict(self._registry.list_all()).get(platform_id, platform_id),
            "auth_status": AuthStatus.authorized.value,
            "degraded": self._registry.is_degraded(platform_id),
        }

    def revoke(self, user_id: str, platform_id: str) -> None:
        repo = AuthorizationRepository(self._session)
        auth = repo.get(platform_id)
        if auth is None or auth.user_id != user_id:
            raise NotFoundError(f"平台未授权: {platform_id}")
        repo.delete(platform_id)
        record_audit(
            self._session,
            AuditAction.REVOKE_AUTHORIZATION,
            f"用户 {user_id} 撤销平台 {platform_id} 授权",
        )
        self._session.commit()
        logger.info("platform_revoked", platform_id=platform_id, user_id=user_id)

    def is_authorized(self, platform_id: str) -> bool:
        """投递引擎与调度任务的授权闸门：撤销后立即返回 False。"""
        auth = AuthorizationRepository(self._session).get(platform_id)
        return auth is not None and auth.status == AuthStatus.authorized

    def authorized_platform_ids(self) -> list[str]:
        repo = AuthorizationRepository(self._session)
        return [
            platform_id
            for platform_id, _ in self._registry.list_all()
            if (auth := repo.get(platform_id)) is not None and auth.status == AuthStatus.authorized
        ]