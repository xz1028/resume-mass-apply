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


def record_audit(session: Session, action: AuditAction, detail: str) -> None:
    """在业务事务内写入审计记录，并输出结构化审计日志。"""
    from app.repositories.repos import AuditRepository

    AuditRepository(session).add(action=action, detail=detail, occurred_at=datetime.now())
    logger.info("audit_event", action=action.value, detail=detail)