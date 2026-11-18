"""通知客户端：NotificationClient 契约（design 8.3）与默认日志实现。

单向推送关键状态事件（面试邀请/不合适）；失败入队暂存并定期重发，不阻塞主流程。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.infra.logging import get_logger

logger = get_logger("notifier")

NOTIFIABLE_STATUSES = {"interview_invited", "rejected"}


@dataclass
class TrackingEvent:
    record_id: str
    user_id: str
    company: str
    title: str
    new_status: str
    occurred_at: datetime


@dataclass
class SendResult:
    success: bool
    error: str | None = None


@runtime_checkable
class NotificationClient(Protocol):
    def send(self, event: TrackingEvent) -> SendResult: ...


class LoggingNotificationClient:
    """默认实现：输出结构化通知日志（可替换为真实通知服务客户端）。"""

    def send(self, event: TrackingEvent) -> SendResult:
        logger.info(
            "notification_sent",
            record_id=event.record_id,
            user_id=event.user_id,
            company=event.company,
            title=event.title,
            new_status=event.new_status,
        )
        return SendResult(success=True)


class FailingNotificationClient:
    """测试用：总是失败，验证通知容错不阻塞主流程。"""

    def send(self, event: TrackingEvent) -> SendResult:
        return SendResult(success=False, error="通知服务不可用（模拟）")


_pending_events: list[TrackingEvent] = []


def enqueue_pending(event: TrackingEvent) -> None:
    _pending_events.append(event)
    logger.warning("notification_enqueued", record_id=event.record_id)


def resend_pending(client: NotificationClient) -> int:
    """定期重发暂存队列；返回本次成功发送数。"""
    sent = 0
    remaining: list[TrackingEvent] = []
    while _pending_events:
        event = _pending_events.pop(0)
        try:
            result = client.send(event)
            if result.success:
                sent += 1
                continue
        except Exception:  # noqa: BLE001
            pass
        remaining.append(event)
    _pending_events.extend(remaining)
    if sent:
        logger.info("notification_resent", count=sent)
    return sent


_notifier: NotificationClient | None = None


def get_notifier() -> NotificationClient:
    global _notifier
    if _notifier is None:
        _notifier = LoggingNotificationClient()
    return _notifier


def set_notifier(client: NotificationClient) -> None:
    global _notifier
    _notifier = client