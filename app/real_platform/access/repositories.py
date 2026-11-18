"""接入治理仓储：配置/挑战/风险事件三仓储。

状态流转幂等（重复 complete/expire 不重复变更）；
终态记录 30 天归档清理；风险事件读取即置 notified。
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.infra.logging import get_logger
from app.real_platform.access.models import (
    CaptchaChallengeRow,
    PlatformAccessConfigRow,
    PlatformRiskEventRow,
)

logger = get_logger("access_repositories")

ARCHIVE_RETENTION_DAYS = 30

RISK_EVENT_ADVICE = {
    "rate_limited": "平台触发限流，系统已自动放缓投递速度，无需处理",
    "account_risk": "平台检测到账号风险，建议暂停该平台投递并稍后手动登录查看",
    "account_restricted": "账号功能受限，请在浏览器中登录平台查看受限原因",
    "interface_changed": "平台页面结构变更导致自动化失效，请等待软件更新适配",
    "account_banned": "账号已被平台封禁，请通过平台官方渠道申诉",
}


class AccessConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, platform_id: str) -> PlatformAccessConfigRow | None:
        return self._session.get(PlatformAccessConfigRow, platform_id)

    def list_all(self) -> list[PlatformAccessConfigRow]:
        return list(
            self._session.scalars(select(PlatformAccessConfigRow).order_by(PlatformAccessConfigRow.priority, PlatformAccessConfigRow.platform_id))
        )

    def ensure_preset(
        self,
        platform_id: str,
        name: str,
        access_mode: str,
        priority: str,
        access_mode_note: str,
        delivery_rate_per_hour: float,
        fetch_interval_hours: int,
    ) -> PlatformAccessConfigRow:
        """预置条目初始化（幂等：已存在时不覆盖用户已改动的字段）。"""
        row = self.get(platform_id)
        if row is None:
            row = PlatformAccessConfigRow(
                platform_id=platform_id,
                name=name,
                access_mode=access_mode,
                priority=priority,
                enabled=False,
                delivery_rate_per_hour=delivery_rate_per_hour,
                fetch_interval_hours=fetch_interval_hours,
                access_mode_note=access_mode_note,
            )
            self._session.add(row)
            self._session.flush()
        return row

    def set_enabled(self, platform_id: str, enabled: bool) -> None:
        self._session.execute(
            update(PlatformAccessConfigRow)
            .where(PlatformAccessConfigRow.platform_id == platform_id)
            .values(enabled=enabled)
        )
        self._session.flush()

    def confirm_risk(self, platform_id: str) -> None:
        self._session.execute(
            update(PlatformAccessConfigRow)
            .where(PlatformAccessConfigRow.platform_id == platform_id)
            .values(risk_confirmed_at=datetime.now())
        )
        self._session.flush()

    def update_rate_policy(self, platform_id: str, rate_per_hour: float) -> None:
        self._session.execute(
            update(PlatformAccessConfigRow)
            .where(PlatformAccessConfigRow.platform_id == platform_id)
            .values(delivery_rate_per_hour=rate_per_hour)
        )
        self._session.flush()


class CaptchaChallengeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, platform_id: str, stage: str, timeout_seconds: int) -> CaptchaChallengeRow:
        now = datetime.now()
        row = CaptchaChallengeRow(
            platform_id=platform_id,
            stage=stage,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def find_pending(self, platform_id: str) -> CaptchaChallengeRow | None:
        """同一时间至多一条 pending 挑战（创建前先查，存在即门闸）。"""
        row = self._session.scalar(
            select(CaptchaChallengeRow)
            .where(
                CaptchaChallengeRow.platform_id == platform_id,
                CaptchaChallengeRow.status == "pending",
            )
            .order_by(CaptchaChallengeRow.created_at.desc())
        )
        return row

    def find_any_pending(self) -> list[CaptchaChallengeRow]:
        return list(
            self._session.scalars(
                select(CaptchaChallengeRow).where(CaptchaChallengeRow.status == "pending")
            )
        )

    def get(self, challenge_id: str) -> CaptchaChallengeRow | None:
        return self._session.get(CaptchaChallengeRow, challenge_id)

    def complete(self, challenge_id: str) -> bool:
        """pending→completed 幂等流转；非 pending 返回 False。"""
        row = self.get(challenge_id)
        if row is None or row.status != "pending":
            return False
        row.status = "completed"
        row.resolved_at = datetime.now()
        self._session.flush()
        return True

    def expire(self, challenge_id: str) -> bool:
        """pending→expired 幂等流转。"""
        row = self.get(challenge_id)
        if row is None or row.status != "pending":
            return False
        row.status = "expired"
        row.resolved_at = datetime.now()
        self._session.flush()
        return True

    def expire_all_overdue(self, platform_id: str | None = None) -> int:
        """超时未完成的 pending 挑战批量置 expired（门闸解除，不阻塞下周期）。"""
        stmt = (
            update(CaptchaChallengeRow)
            .where(
                CaptchaChallengeRow.status == "pending",
                CaptchaChallengeRow.expires_at < datetime.now(),
            )
            .values(status="expired", resolved_at=datetime.now())
        )
        if platform_id:
            stmt = stmt.where(CaptchaChallengeRow.platform_id == platform_id)
        result = self._session.execute(stmt)
        self._session.flush()
        return int(result.rowcount or 0)

    def archive_terminal(self) -> int:
        """终态（completed/expired）记录 30 天归档清理。"""
        cutoff = datetime.now() - timedelta(days=ARCHIVE_RETENTION_DAYS)
        result = self._session.execute(
            delete(CaptchaChallengeRow).where(
                CaptchaChallengeRow.status.in_(["completed", "expired"]),
                CaptchaChallengeRow.resolved_at.is_not(None),
                CaptchaChallengeRow.resolved_at < cutoff,
            )
        )
        self._session.flush()
        return int(result.rowcount or 0)


class RiskEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, platform_id: str, event_type: str, detail: str = "") -> PlatformRiskEventRow:
        advice = RISK_EVENT_ADVICE.get(event_type, "请关注平台账号状态")
        row = PlatformRiskEventRow(
            platform_id=platform_id,
            event_type=event_type,
            advice=advice,
            notified=False,
            occurred_at=datetime.now(),
        )
        self._session.add(row)
        self._session.flush()
        logger.warning(
            "platform_risk_event",
            platform_id=platform_id,
            event_type=event_type,
            detail=detail,
            advice=advice,
        )
        return row

    def list_unnotified(self) -> list[PlatformRiskEventRow]:
        return list(
            self._session.scalars(
                select(PlatformRiskEventRow)
                .where(PlatformRiskEventRow.notified.is_(False))
                .order_by(PlatformRiskEventRow.occurred_at)
            )
        )

    def mark_notified_batch(self, event_ids: list[str]) -> int:
        if not event_ids:
            return 0
        result = self._session.execute(
            update(PlatformRiskEventRow)
            .where(PlatformRiskEventRow.event_id.in_(event_ids))
            .values(notified=True)
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def archive_terminal(self) -> int:
        """已告知事件 30 天归档清理。"""
        cutoff = datetime.now() - timedelta(days=ARCHIVE_RETENTION_DAYS)
        result = self._session.execute(
            delete(PlatformRiskEventRow).where(
                PlatformRiskEventRow.notified.is_(True),
                PlatformRiskEventRow.occurred_at < cutoff,
            )
        )
        self._session.flush()
        return int(result.rowcount or 0)