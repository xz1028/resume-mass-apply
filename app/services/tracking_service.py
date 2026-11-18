"""投递状态跟踪服务：状态定期同步（幂等）、关键状态通知、投递统计。

同步失败容错：保留上次状态、记录失败日志、等待下周期重试。
通知容错：通知发送在状态落库事务之外执行，失败入队暂存并定期重发。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.config import DEFAULT_USER_ID
from app.domain.models import AuthStatus, DeliveryStatus
from app.domain.state_machine import IllegalTransitionError, transition
from app.infra.logging import get_logger
from app.infra.metrics import set_status_distribution
from app.infra.notifier import (
    NOTIFIABLE_STATUSES,
    NotificationClient,
    TrackingEvent,
    enqueue_pending,
)
from app.platforms.registry import AdapterRegistry
from app.platforms.spi import PlatformError, PlatformRecordRef
from app.repositories.repos import (
    AuthorizationRepository,
    PositionRepository,
    RecordRepository,
)

logger = get_logger("tracking_service")


class TrackingService:
    def __init__(
        self,
        session: Session,
        registry: AdapterRegistry,
        notifier: NotificationClient,
    ) -> None:
        self._session = session
        self._registry = registry
        self._notifier = notifier

    def sync_status(self, user_id: str = DEFAULT_USER_ID) -> dict:
        """周期同步：拉取平台回执，经状态机校验后更新投递记录状态。"""
        record_repo = RecordRepository(self._session)
        pos_repo = PositionRepository(self._session)
        syncable = record_repo.list_syncable(user_id)
        if not syncable:
            return {"synced": 0, "skipped": 0}

        by_platform: dict[str, list] = {}
        for record in syncable:
            by_platform.setdefault(record.platform_id, []).append(record)

        synced = 0
        skipped = 0
        for platform_id, records in by_platform.items():
            auth = AuthorizationRepository(self._session).get(platform_id)
            if auth is None or auth.status != AuthStatus.authorized:
                continue
            adapter = self._registry.get(platform_id)
            if adapter is None:
                continue
            refs = [
                PlatformRecordRef(
                    record_id=r.record_id, platform_record_ref=r.platform_record_ref or ""
                )
                for r in records
            ]
            try:
                receipts = adapter.fetch_application_status(refs)
                self._registry.record_call_success(platform_id)
            except PlatformError as exc:
                self._registry.record_call_failure(platform_id)
                logger.warning("status_sync_failed", platform_id=platform_id, error=str(exc))
                continue

            ref_to_record = {r.platform_record_ref: r for r in records if r.platform_record_ref}
            for receipt in receipts:
                record = ref_to_record.get(receipt.record_ref)
                if record is None:
                    continue
                idem = (
                    f"{platform_id}|{receipt.record_ref}|{receipt.receipt_seq}"
                    f"|{receipt.receipt_time.isoformat()}"
                )
                if record.idempotency_key == idem:
                    skipped += 1
                    continue
                try:
                    transition(record.status, receipt.new_status)
                except IllegalTransitionError:
                    skipped += 1
                    logger.warning(
                        "status_sync_rejected",
                        record_id=record.record_id,
                        current=record.status.value,
                        target=receipt.new_status.value,
                    )
                    continue
                old_status = record.status
                record_repo.update_status(
                    record.record_id,
                    receipt.new_status,
                    receipt.receipt_time,
                    idempotency_key=idem,
                )
                synced += 1
                logger.info(
                    "status_synced",
                    record_id=record.record_id,
                    old_status=old_status.value,
                    new_status=receipt.new_status.value,
                )
                if receipt.new_status.value in NOTIFIABLE_STATUSES:
                    self._notify(user_id, record, receipt.new_status, receipt.receipt_time)

        self._session.commit()
        stats = record_repo.statistics(user_id)
        set_status_distribution(stats["status_distribution"])
        return {"synced": synced, "skipped": skipped}

    def _notify(
        self,
        user_id: str,
        record,
        new_status: DeliveryStatus,
        occurred_at: datetime,
    ) -> None:
        """关键状态通知：内容包含公司名与职位名；失败入队暂存。"""
        position = PositionRepository(self._session).get(record.position_id)
        event = TrackingEvent(
            record_id=record.record_id,
            user_id=user_id,
            company=position.company if position else "未知公司",
            title=position.title if position else "未知职位",
            new_status=new_status.value,
            occurred_at=occurred_at,
        )
        try:
            result = self._notifier.send(event)
            if not result.success:
                enqueue_pending(event)
        except Exception:  # noqa: BLE001
            enqueue_pending(event)

    def statistics(self, user_id: str) -> dict:
        return RecordRepository(self._session).statistics(user_id)

    def list_records(
        self,
        user_id: str,
        status: str | None = None,
        platform_id: str | None = None,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        """数据隔离：仅返回当前求职者本人的投递记录。"""
        return RecordRepository(self._session).list_by_user(
            user_id,
            status=status,
            platform_id=platform_id,
            since=since,
            page=page,
            page_size=page_size,
        )