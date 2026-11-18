"""投递记录状态机：合法迁移表 + 非法迁移拒绝与告警。

待投递→已投递/投递失败/已过期；已投递→已查看/面试邀请/不合适/已过期；
已查看→面试邀请/不合适；面试邀请→不合适；
终态（投递失败/已过期/不合适）不可迁移。
"""

from app.domain.models import DeliveryStatus
from app.infra.logging import get_logger

logger = get_logger("state_machine")

ALLOWED_TRANSITIONS: dict[DeliveryStatus, frozenset[DeliveryStatus]] = {
    DeliveryStatus.pending: frozenset({
        DeliveryStatus.delivered,
        DeliveryStatus.failed,
        DeliveryStatus.expired,
    }),
    DeliveryStatus.delivered: frozenset({
        DeliveryStatus.viewed,
        DeliveryStatus.interview_invited,
        DeliveryStatus.rejected,
        DeliveryStatus.expired,
    }),
    DeliveryStatus.viewed: frozenset({
        DeliveryStatus.interview_invited,
        DeliveryStatus.rejected,
    }),
    DeliveryStatus.interview_invited: frozenset({
        DeliveryStatus.rejected,
    }),
    DeliveryStatus.failed: frozenset(),
    DeliveryStatus.expired: frozenset(),
    DeliveryStatus.rejected: frozenset(),
}

TERMINAL_STATUSES: frozenset[DeliveryStatus] = frozenset({
    DeliveryStatus.failed,
    DeliveryStatus.expired,
    DeliveryStatus.rejected,
})


class IllegalTransitionError(Exception):
    def __init__(self, current: DeliveryStatus, target: DeliveryStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"非法状态迁移: {current.value} -> {target.value}")


def transition(current: DeliveryStatus, target: DeliveryStatus) -> DeliveryStatus:
    """校验并执行状态迁移；非法迁移拒绝变更并记录告警日志。"""
    if target not in ALLOWED_TRANSITIONS[current]:
        logger.warning(
            "illegal_delivery_status_transition",
            current=current.value,
            target=target.value,
        )
        raise IllegalTransitionError(current, target)
    return target