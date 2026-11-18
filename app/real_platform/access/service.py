"""PlatformAccessService 核心治理：配置管理、风险确认门禁、启停联动、限流上限闸门、单账号边界。"""

from app.api.v1.errors import (
    InvalidParamError,
    NotFoundError,
    PlatformAlreadyAuthorizedError,
    RatePolicyExceededError,
    RiskUnconfirmedError,
)
from app.config import settings
from app.domain.models import AuthStatus
from app.infra.audit import AuditAction, record_audit
from app.infra.logging import get_logger
from app.infra.rate_limiter import get_rate_limiters
from app.platforms.registry import AdapterRegistry
from app.real_platform.access.repositories import AccessConfigRepository
from app.repositories.repos import AuthorizationRepository

logger = get_logger("access_service")


class PlatformAccessService:
    def __init__(self, session, registry: AdapterRegistry) -> None:
        self._session = session
        self._registry = registry

    # ---------- 配置查询 ----------

    def list_configs(self) -> list[dict]:
        rows = AccessConfigRepository(self._session).list_all()
        auth_repo = AuthorizationRepository(self._session)
        result = []
        for row in rows:
            auth = auth_repo.get(row.platform_id)
            result.append(
                {
                    "platform_id": row.platform_id,
                    "name": row.name,
                    "access_mode": row.access_mode,
                    "priority": row.priority,
                    "enabled": row.enabled,
                    "risk_confirmed": row.risk_confirmed_at is not None,
                    "auth_status": auth.status.value if auth else AuthStatus.unauthorized.value,
                    "degraded": self._registry.is_degraded(row.platform_id),
                    "delivery_rate_per_hour": row.delivery_rate_per_hour,
                    "fetch_interval_hours": row.fetch_interval_hours,
                    "access_mode_note": row.access_mode_note,
                }
            )
        return result

    def get_config(self, platform_id: str) -> dict:
        row = AccessConfigRepository(self._session).get(platform_id)
        if row is None:
            raise NotFoundError(f"平台接入配置不存在: {platform_id}")
        auth = AuthorizationRepository(self._session).get(platform_id)
        return {
            "platform_id": row.platform_id,
            "name": row.name,
            "access_mode": row.access_mode,
            "priority": row.priority,
            "enabled": row.enabled,
            "risk_confirmed": row.risk_confirmed_at is not None,
            "auth_status": auth.status.value if auth else AuthStatus.unauthorized.value,
            "degraded": self._registry.is_degraded(row.platform_id),
            "delivery_rate_per_hour": row.delivery_rate_per_hour,
            "fetch_interval_hours": row.fetch_interval_hours,
            "access_mode_note": row.access_mode_note,
        }

    # ---------- 风险确认门禁 ----------

    def confirm_risk(self, platform_id: str) -> None:
        repo = AccessConfigRepository(self._session)
        if repo.get(platform_id) is None:
            raise NotFoundError(f"平台接入配置不存在: {platform_id}")
        repo.confirm_risk(platform_id)
        record_audit(
            self._session,
            AuditAction.PLATFORM_RISK_CONFIRMED,
            f"用户确认平台 {platform_id} 接入风险告知",
        )
        self._session.commit()

    # ---------- 启停联动 ----------

    def enable(self, platform_id: str) -> dict:
        repo = AccessConfigRepository(self._session)
        row = repo.get(platform_id)
        if row is None:
            raise NotFoundError(f"平台接入配置不存在: {platform_id}")
        if row.risk_confirmed_at is None:
            raise RiskUnconfirmedError("请先阅读并确认平台接入风险告知")
        if row.enabled:
            return {"platform_id": platform_id, "enabled": True}  # 幂等
        adapter = self._build_adapter(platform_id)
        self._registry.register(adapter, name=row.name)
        get_rate_limiters().set_policy(platform_id, row.delivery_rate_per_hour)
        repo.set_enabled(platform_id, True)
        record_audit(self._session, AuditAction.PLATFORM_ENABLED, f"启用平台 {platform_id}")
        self._session.commit()
        logger.info("platform_enabled", platform_id=platform_id, rate=row.delivery_rate_per_hour)
        return {"platform_id": platform_id, "enabled": True}

    def disable(self, platform_id: str) -> dict:
        repo = AccessConfigRepository(self._session)
        row = repo.get(platform_id)
        if row is None:
            raise NotFoundError(f"平台接入配置不存在: {platform_id}")
        if not row.enabled:
            return {"platform_id": platform_id, "enabled": False}  # 幂等
        self._registry.unregister(platform_id)
        from app.real_platform.browser.session_manager import get_session_manager

        get_session_manager().terminate(platform_id)
        repo.set_enabled(platform_id, False)
        record_audit(self._session, AuditAction.PLATFORM_DISABLED, f"禁用平台 {platform_id}，历史记录保留")
        self._session.commit()
        logger.info("platform_disabled", platform_id=platform_id)
        return {"platform_id": platform_id, "enabled": False}

    # ---------- 限流安全上限闸门 ----------

    def update_rate_policy(self, platform_id: str, rate_per_hour: float) -> dict:
        repo = AccessConfigRepository(self._session)
        row = repo.get(platform_id)
        if row is None:
            raise NotFoundError(f"平台接入配置不存在: {platform_id}")
        if rate_per_hour < 1 or rate_per_hour > settings.delivery_hard_limit_per_hour:
            raise RatePolicyExceededError(
                f"限流设置超过安全上限（投递 ≤{settings.delivery_hard_limit_per_hour}/小时）"
            )
        repo.update_rate_policy(platform_id, rate_per_hour)
        if row.enabled:
            get_rate_limiters().set_policy(platform_id, rate_per_hour)
        record_audit(
            self._session,
            AuditAction.RATE_POLICY_CHANGED,
            f"平台 {platform_id} 投递限流调整为 {rate_per_hour}/小时",
        )
        self._session.commit()
        return {"platform_id": platform_id, "delivery_rate_per_hour": rate_per_hour}

    # ---------- 单账号边界 ----------

    def ensure_no_existing_authorization(self, platform_id: str) -> None:
        auth = AuthorizationRepository(self._session).get(platform_id)
        if auth is not None and auth.status == AuthStatus.authorized:
            raise PlatformAlreadyAuthorizedError("该平台已绑定授权凭证，请先撤销后再授权")

    def credential_exists(self, platform_id: str) -> bool:
        auth = AuthorizationRepository(self._session).get(platform_id)
        return auth is not None

    @staticmethod
    def _build_adapter(platform_id: str):
        from app.real_platform.adapters.boss_zhipin import BossZhipinAdapter
        from app.real_platform.adapters.job51 import Job51Adapter
        from app.real_platform.adapters.zhilian import ZhilianAdapter
        from app.real_platform.access.repositories import AccessConfigRepository

        factory = {
            "boss_zhipin": BossZhipinAdapter,
            "zhilian": ZhilianAdapter,
            "job51": Job51Adapter,
        }
        cls = factory.get(platform_id)
        if cls is None:
            raise InvalidParamError(f"未知真实平台: {platform_id}")
        return cls(rate_per_hour=settings.real_platform_default_rate_per_hour)