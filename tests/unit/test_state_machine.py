"""状态机单元测试：全部合法/非法迁移路径（spec 5.5.1.1）。"""

import pytest

from app.domain.models import DeliveryStatus
from app.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    IllegalTransitionError,
    TERMINAL_STATUSES,
    transition,
)

LEGAL_TRANSITIONS = [
    (DeliveryStatus.pending, DeliveryStatus.delivered),
    (DeliveryStatus.pending, DeliveryStatus.failed),
    (DeliveryStatus.pending, DeliveryStatus.expired),
    (DeliveryStatus.delivered, DeliveryStatus.viewed),
    (DeliveryStatus.delivered, DeliveryStatus.interview_invited),
    (DeliveryStatus.delivered, DeliveryStatus.rejected),
    (DeliveryStatus.delivered, DeliveryStatus.expired),
    (DeliveryStatus.viewed, DeliveryStatus.interview_invited),
    (DeliveryStatus.viewed, DeliveryStatus.rejected),
    (DeliveryStatus.interview_invited, DeliveryStatus.rejected),
]

ILLEGAL_TRANSITIONS = [
    (DeliveryStatus.rejected, DeliveryStatus.viewed),
    (DeliveryStatus.failed, DeliveryStatus.delivered),
    (DeliveryStatus.expired, DeliveryStatus.viewed),
    (DeliveryStatus.viewed, DeliveryStatus.delivered),
    (DeliveryStatus.interview_invited, DeliveryStatus.viewed),
    (DeliveryStatus.pending, DeliveryStatus.viewed),
]


@pytest.mark.parametrize(("current", "target"), LEGAL_TRANSITIONS)
def test_legal_transition(current: DeliveryStatus, target: DeliveryStatus) -> None:
    assert transition(current, target) == target


@pytest.mark.parametrize(("current", "target"), ILLEGAL_TRANSITIONS)
def test_illegal_transition_rejected(
    current: DeliveryStatus, target: DeliveryStatus
) -> None:
    with pytest.raises(IllegalTransitionError):
        transition(current, target)


def test_terminal_states_frozen() -> None:
    """终态（投递失败/已过期/不合适）不可迁移到任何状态。"""
    for terminal in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()
        for target in DeliveryStatus:
            with pytest.raises(IllegalTransitionError):
                transition(terminal, target)


def test_rejected_cannot_become_viewed() -> None:
    """spec 5.5.1.1.b：'不合适'不可再变更为'已查看'。"""
    with pytest.raises(IllegalTransitionError):
        transition(DeliveryStatus.rejected, DeliveryStatus.viewed)


def test_all_statuses_covered() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(DeliveryStatus)