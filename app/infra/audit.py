"""审计日志：授权、撤销授权、发起批量投递、确认投递四类关键操作强制记录。"""

from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.infra.logging import get_logger

logger = get_logger("audit")


class AuditAction(str, Enum):
    AUTHORIZE = "authorize"
    REVOKE_AUTHORIZATION = "revoke_authorization"
    CREATE_DELIVERY_TASK = "create_delivery_task"
    CONFIRM_DELIVERY_TASK = "confirm_delivery_task"
    PLATFORM_RISK_CONFIRMED = "platform_risk_confirmed"
    PLATFORM_ENABLED = "platform_enabled"
    PLATFORM_DISABLED = "platform_disabled"
    RATE_POLICY_CHANGED = "rate_policy_changed"
    BROWSER_AUTH_SESSION = "browser_auth_session"
    AI_KEY_UPDATED = "ai_key_updated"
    AI_PROVIDER_SWITCHED = "ai_provider_switched"
    AI_PRIVACY_SETTINGS_CHANGED = "ai_privacy_settings_changed"
    AI_FEATURE_TOGGLED = "ai_feature_toggled"


def record_audit(session: Session, action: AuditAction, detail: str) -> None:
    """在业务事务内写入审计记录，并输出结构化审计日志。"""
    from app.repositories.repos import AuditRepository

    AuditRepository(session).add(action=action, detail=detail, occurred_at=datetime.now())
    logger.info("audit_event", action=action.value, detail=detail)