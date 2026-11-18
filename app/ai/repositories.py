"""AI 组件仓储层：配置/匹配缓存/招呼语/调用记录/批任务五仓储。

TTL 过期读取跳过；LRU 容量淘汰（批任务尾部顺带执行）；
Key 列为密文，仓储永不解密（解密仅发生在 LLM 客户端调用瞬间）。
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.ai.models import (
    AiBatchTaskRow,
    AiCallLogRow,
    AiGreetingRow,
    AiMatchResultRow,
    AiModelConfigRow,
)
from app.config import settings
from app.infra.logging import get_logger

logger = get_logger("ai_repositories")


class ModelConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, row: AiModelConfigRow) -> AiModelConfigRow:
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, config_id: str) -> AiModelConfigRow | None:
        return self._session.get(AiModelConfigRow, config_id)

    def get_by_name(self, name: str) -> AiModelConfigRow | None:
        return self._session.scalar(
            select(AiModelConfigRow).where(AiModelConfigRow.name == name)
        )

    def list_all(self) -> list[AiModelConfigRow]:
        return list(self._session.scalars(select(AiModelConfigRow).order_by(AiModelConfigRow.created_at)))

    def get_active(self) -> AiModelConfigRow | None:
        return self._session.scalar(
            select(AiModelConfigRow).where(AiModelConfigRow.is_active.is_(True))
        )

    def update_fields(self, config_id: str, **values) -> None:
        self._session.execute(
            update(AiModelConfigRow).where(AiModelConfigRow.config_id == config_id).values(**values)
        )
        self._session.flush()

    def activate_exclusive(self, config_id: str) -> None:
        """事务内两 UPDATE（清旧 + 设新）原子切换；部分唯一索引物理兜底。"""
        self._session.execute(
            update(AiModelConfigRow)
            .where(AiModelConfigRow.is_active.is_(True), AiModelConfigRow.config_id != config_id)
            .values(is_active=False)
        )
        self._session.execute(
            update(AiModelConfigRow)
            .where(AiModelConfigRow.config_id == config_id)
            .values(is_active=True, degraded_until=None, degraded_reason="")
        )
        self._session.flush()

    def delete(self, config_id: str) -> bool:
        row = self.get(config_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


class AiMatchCacheRepository:
    """AI 匹配结果缓存：复合键 (user_id, resume_hash, position_id, jd_hash)。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, user_id: str, resume_hash: str, position_id: str, jd_hash: str) -> AiMatchResultRow | None:
        row = self._session.scalar(
            select(AiMatchResultRow).where(
                AiMatchResultRow.user_id == user_id,
                AiMatchResultRow.resume_hash == resume_hash,
                AiMatchResultRow.position_id == position_id,
                AiMatchResultRow.jd_hash == jd_hash,
            )
        )
        if row is None:
            return None
        if row.generated_at < datetime.now() - timedelta(seconds=settings.ai_match_cache_ttl_seconds):
            return None  # TTL 过期读取跳过
        return row

    def save(self, user_id: str, resume_hash: str, position_id: str, jd_hash: str, score: int, reason: str) -> None:
        existing = self._session.scalar(
            select(AiMatchResultRow).where(
                AiMatchResultRow.user_id == user_id,
                AiMatchResultRow.resume_hash == resume_hash,
                AiMatchResultRow.position_id == position_id,
                AiMatchResultRow.jd_hash == jd_hash,
            )
        )
        if existing is not None:
            existing.score = score
            existing.reason = reason
            existing.generated_at = datetime.now()
        else:
            self._session.add(
                AiMatchResultRow(
                    user_id=user_id,
                    resume_hash=resume_hash,
                    position_id=position_id,
                    jd_hash=jd_hash,
                    score=score,
                    reason=reason,
                    generated_at=datetime.now(),
                )
            )
        self._session.flush()

    def lru_cleanup(self) -> int:
        """容量 2000 行 LRU 清理（批任务尾部顺带执行）。"""
        total = self._session.scalar(
            select(func.count()).select_from(AiMatchResultRow)
        ) or 0
        if total <= settings.ai_cache_capacity:
            return 0
        overflow = total - settings.ai_cache_capacity
        stale_ids = list(
            self._session.scalars(
                select(AiMatchResultRow.id)
                .order_by(AiMatchResultRow.generated_at.asc())
                .limit(overflow)
            )
        )
        if stale_ids:
            self._session.execute(
                delete(AiMatchResultRow).where(AiMatchResultRow.id.in_(stale_ids))
            )
            self._session.flush()
        return len(stale_ids)


class AiGreetingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, user_id: str, resume_hash: str, position_id: str, jd_hash: str) -> AiGreetingRow | None:
        row = self._session.scalar(
            select(AiGreetingRow).where(
                AiGreetingRow.user_id == user_id,
                AiGreetingRow.resume_hash == resume_hash,
                AiGreetingRow.position_id == position_id,
                AiGreetingRow.jd_hash == jd_hash,
            ).order_by(AiGreetingRow.generated_at.desc())
        )
        if row is None:
            return None
        if row.generated_at < datetime.now() - timedelta(seconds=settings.ai_greeting_cache_ttl_seconds):
            return None
        return row

    def find_by_task(self, delivery_task_id: str) -> list[AiGreetingRow]:
        return list(
            self._session.scalars(
                select(AiGreetingRow)
                .where(AiGreetingRow.delivery_task_id == delivery_task_id)
                .order_by(AiGreetingRow.generated_at)
            )
        )

    def find_by_task_and_position(self, delivery_task_id: str, position_id: str) -> AiGreetingRow | None:
        return self._session.scalar(
            select(AiGreetingRow)
            .where(
                AiGreetingRow.delivery_task_id == delivery_task_id,
                AiGreetingRow.position_id == position_id,
            )
            .order_by(AiGreetingRow.generated_at.desc())
        )

    def save(
        self,
        user_id: str,
        resume_hash: str,
        position_id: str,
        jd_hash: str,
        delivery_task_id: str,
        text: str,
        source: str,
    ) -> AiGreetingRow:
        self._session.add(
            AiGreetingRow(
                user_id=user_id,
                resume_hash=resume_hash,
                position_id=position_id,
                jd_hash=jd_hash,
                delivery_task_id=delivery_task_id,
                text=text,
                source=source,
                generated_at=datetime.now(),
            )
        )
        self._session.flush()
        row = self._session.scalar(
            select(AiGreetingRow).where(
                AiGreetingRow.delivery_task_id == delivery_task_id,
                AiGreetingRow.position_id == position_id,
            ).order_by(AiGreetingRow.generated_at.desc())
        )
        return row

    def set_edited(self, delivery_task_id: str, position_id: str, edited_text: str) -> bool:
        row = self._session.scalar(
            select(AiGreetingRow)
            .where(
                AiGreetingRow.delivery_task_id == delivery_task_id,
                AiGreetingRow.position_id == position_id,
            )
            .order_by(AiGreetingRow.generated_at.desc())
        )
        if row is None:
            return False
        row.edited_text = edited_text
        self._session.flush()
        return True


class AiCallLogRepository:
    """只追加 + 环形淘汰 2000 条。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self, provider: str, call_type: str, result: str, failure_kind: str, duration_ms: int, attempted: int
    ) -> None:
        self._session.add(
            AiCallLogRow(
                provider=provider,
                call_type=call_type,
                result=result,
                failure_kind=failure_kind or "",
                duration_ms=duration_ms,
                attempted=attempted,
                created_at=datetime.now(),
            )
        )
        self._session.flush()

    def ring_cleanup(self) -> int:
        total = self._session.scalar(select(func.count()).select_from(AiCallLogRow)) or 0
        if total <= settings.ai_call_log_capacity:
            return 0
        overflow = total - settings.ai_call_log_capacity
        stale_ids = list(
            self._session.scalars(
                select(AiCallLogRow.id).order_by(AiCallLogRow.created_at.asc()).limit(overflow)
            )
        )
        if stale_ids:
            self._session.execute(delete(AiCallLogRow).where(AiCallLogRow.id.in_(stale_ids)))
            self._session.flush()
        return len(stale_ids)


class AiBatchTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, kind: str, user_id: str, top_n: int, delivery_task_id: str = "", total: int = 0) -> AiBatchTaskRow:
        row = AiBatchTaskRow(
            kind=kind,
            user_id=user_id,
            top_n=top_n,
            delivery_task_id=delivery_task_id,
            status="pending",
            total=total,
            done=0,
            fallback_count=0,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, task_id: str) -> AiBatchTaskRow | None:
        return self._session.get(AiBatchTaskRow, task_id)

    def find_recent_running(self, kind: str, user_id: str, top_n: int) -> AiBatchTaskRow | None:
        """60 秒幂等窗口内同参数未完成任务直接复用。"""
        cutoff = datetime.now() - timedelta(seconds=settings.ai_matching_task_idempotent_window_seconds)
        return self._session.scalar(
            select(AiBatchTaskRow).where(
                AiBatchTaskRow.kind == kind,
                AiBatchTaskRow.user_id == user_id,
                AiBatchTaskRow.top_n == top_n,
                AiBatchTaskRow.status.in_(["pending", "running"]),
                AiBatchTaskRow.created_at >= cutoff,
            ).order_by(AiBatchTaskRow.created_at.desc())
        )

    def update_progress(self, task_id: str, done: int, fallback_count: int, status: str | None = None) -> None:
        values = {"done": done, "fallback_count": fallback_count, "updated_at": datetime.now()}
        if status is not None:
            values["status"] = status
        self._session.execute(
            update(AiBatchTaskRow).where(AiBatchTaskRow.task_id == task_id).values(**values)
        )
        self._session.flush()

    def set_status(self, task_id: str, status: str, degrade_message: str = "") -> None:
        self._session.execute(
            update(AiBatchTaskRow)
            .where(AiBatchTaskRow.task_id == task_id)
            .values(status=status, degrade_message=degrade_message, updated_at=datetime.now())
        )
        self._session.flush()

    def lru_cleanup(self) -> int:
        """终态任务 LRU 32 条淘汰。"""
        total = self._session.scalar(select(func.count()).select_from(AiBatchTaskRow)) or 0
        if total <= settings.ai_batch_task_retention:
            return 0
        terminal = list(
            self._session.scalars(
                select(AiBatchTaskRow.id)
                .where(AiBatchTaskRow.status.in_(["completed", "rejected", "cancelled"]))
                .order_by(AiBatchTaskRow.updated_at.asc())
                .limit(total - settings.ai_batch_task_retention)
            )
        )
        if terminal:
            self._session.execute(delete(AiBatchTaskRow).where(AiBatchTaskRow.id.in_(terminal)))
            self._session.flush()
        return len(terminal)