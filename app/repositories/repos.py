"""各实体 Repository：领域对象与 ORM 行互转，领域层不感知 SQLAlchemy。"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.domain.models import (
    AuditLog,
    AuthStatus,
    BlacklistEntry,
    BlacklistType,
    ContactInfo,
    DeliveryRecord,
    DeliveryStatus,
    DeliveryTask,
    JobIntention,
    JobPosition,
    JobSeekerProfile,
    PlatformAuthorization,
    ResumeFormat,
    ResumeProfile,
    ResumeSnapshot,
    TaskStatus,
)
from app.repositories.orm import (
    AppSettingRow,
    AuditLogRow,
    BlacklistEntryRow,
    DeliveryRecordRow,
    DeliveryTaskRow,
    JobPositionRow,
    PlatformAuthorizationRow,
    ResumeProfileRow,
    SeekerProfileRow,
)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class SeekerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self, user_id: str) -> JobSeekerProfile:
        row = self._session.get(SeekerProfileRow, user_id)
        if row is None:
            row = SeekerProfileRow(user_id=user_id, contact={}, intention={})
            self._session.add(row)
            self._session.flush()
        return JobSeekerProfile(
            user_id=row.user_id,
            contact=ContactInfo(**(row.contact or {})),
            intention=JobIntention.from_dict(row.intention),
        )

    def save(self, profile: JobSeekerProfile) -> None:
        row = self._session.get(SeekerProfileRow, profile.user_id)
        if row is None:
            row = SeekerProfileRow(user_id=profile.user_id, contact={}, intention={})
            self._session.add(row)
        row.contact = {
            "phone": profile.contact.phone,
            "email": profile.contact.email,
        }
        row.intention = profile.intention.to_dict()
        self._session.flush()


class ResumeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: ResumeProfileRow) -> ResumeProfile:
        return ResumeProfile(
            resume_id=row.resume_id,
            user_id=row.user_id,
            name=row.name,
            format=ResumeFormat(row.format),
            size_bytes=row.size_bytes,
            is_default=row.is_default,
            created_at=row.created_at,
            storage_ref=row.storage_ref,
        )

    def add(self, resume: ResumeProfile) -> ResumeProfile:
        if self.exists_name(resume.user_id, resume.name):
            from app.domain.models import DuplicateResumeNameError

            raise DuplicateResumeNameError(f"简历档案名称已存在: {resume.name}")
        row = ResumeProfileRow(
            resume_id=resume.resume_id,
            user_id=resume.user_id,
            name=resume.name,
            format=resume.format.value,
            size_bytes=resume.size_bytes,
            is_default=resume.is_default,
            created_at=resume.created_at,
            storage_ref=resume.storage_ref,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_domain(row)

    def get(self, user_id: str, resume_id: str) -> ResumeProfile | None:
        row = self._session.get(ResumeProfileRow, resume_id)
        if row is None or row.user_id != user_id:
            return None
        return self._to_domain(row)

    def get_default(self, user_id: str) -> ResumeProfile | None:
        row = self._session.scalar(
            select(ResumeProfileRow).where(
                ResumeProfileRow.user_id == user_id,
                ResumeProfileRow.is_default.is_(True),
            )
        )
        return self._to_domain(row) if row else None

    def list_by_user(self, user_id: str) -> list[ResumeProfile]:
        rows = self._session.scalars(
            select(ResumeProfileRow)
            .where(ResumeProfileRow.user_id == user_id)
            .order_by(ResumeProfileRow.created_at.desc())
        ).all()
        return [self._to_domain(r) for r in rows]

    def exists_name(self, user_id: str, name: str, exclude_id: str | None = None) -> bool:
        stmt = select(func.count()).select_from(ResumeProfileRow).where(
            ResumeProfileRow.user_id == user_id,
            ResumeProfileRow.name == name,
        )
        if exclude_id:
            stmt = stmt.where(ResumeProfileRow.resume_id != exclude_id)
        return bool(self._session.scalar(stmt))

    def rename(self, user_id: str, resume_id: str, name: str) -> ResumeProfile:
        row = self._session.get(ResumeProfileRow, resume_id)
        if row is None or row.user_id != user_id:
            raise LookupError(f"简历档案不存在: {resume_id}")
        if self.exists_name(user_id, name, exclude_id=resume_id):
            from app.domain.models import DuplicateResumeNameError

            raise DuplicateResumeNameError(f"简历档案名称已存在: {name}")
        row.name = name
        self._session.flush()
        return self._to_domain(row)

    def set_default(self, user_id: str, resume_id: str) -> ResumeProfile:
        """单事务内先清除旧默认再设置新默认，保证最多一个默认。"""
        row = self._session.get(ResumeProfileRow, resume_id)
        if row is None or row.user_id != user_id:
            raise LookupError(f"简历档案不存在: {resume_id}")
        self._session.execute(
            update(ResumeProfileRow)
            .where(ResumeProfileRow.user_id == user_id, ResumeProfileRow.is_default.is_(True))
            .values(is_default=False)
        )
        row.is_default = True
        self._session.flush()
        defaults = self._session.scalar(
            select(func.count()).select_from(ResumeProfileRow).where(
                ResumeProfileRow.user_id == user_id,
                ResumeProfileRow.is_default.is_(True),
            )
        )
        if defaults and defaults > 1:
            from app.domain.models import MultipleDefaultResumeError

            raise MultipleDefaultResumeError("默认简历档案数超过 1")
        return self._to_domain(row)

    def delete(self, user_id: str, resume_id: str) -> None:
        row = self._session.get(ResumeProfileRow, resume_id)
        if row is None or row.user_id != user_id:
            raise LookupError(f"简历档案不存在: {resume_id}")
        self._session.delete(row)
        self._session.flush()


class PositionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: JobPositionRow) -> JobPosition:
        return JobPosition(
            position_id=row.position_id,
            platform_id=row.platform_id,
            title=row.title,
            company=row.company,
            city=row.city,
            salary_min=row.salary_min,
            salary_max=row.salary_max,
            industry=row.industry,
            experience_req=row.experience_req,
            publish_expire_at=row.publish_expire_at,
            fetched_at=row.fetched_at,
            expired=row.expired,
            jd_text=row.jd_text,
            jd_fetched_at=row.jd_fetched_at,
        )

    def upsert(self, position: JobPosition) -> JobPosition:
        """以（platform_id + position_id）为唯一键去重，重复仅保留最新一条。"""
        row = self._session.scalar(
            select(JobPositionRow).where(
                JobPositionRow.platform_id == position.platform_id,
                JobPositionRow.position_id == position.position_id,
            )
        )
        if row is None:
            row = JobPositionRow(
                platform_id=position.platform_id,
                position_id=position.position_id,
                title=position.title,
                company=position.company,
                city=position.city,
                salary_min=position.salary_min,
                salary_max=position.salary_max,
                industry=position.industry,
                experience_req=position.experience_req,
                publish_expire_at=position.publish_expire_at,
                fetched_at=position.fetched_at,
                expired=position.expired,
                jd_text=position.jd_text,
                jd_fetched_at=position.jd_fetched_at,
            )
            self._session.add(row)
        else:
            row.title = position.title
            row.company = position.company
            row.city = position.city
            row.salary_min = position.salary_min
            row.salary_max = position.salary_max
            row.industry = position.industry
            row.experience_req = position.experience_req
            row.publish_expire_at = position.publish_expire_at
            row.fetched_at = position.fetched_at
            row.expired = position.expired
            if position.jd_text is not None:
                row.jd_text = position.jd_text
                row.jd_fetched_at = position.jd_fetched_at
        self._session.flush()
        return self._to_domain(row)

    def get(self, position_id: str) -> JobPosition | None:
        row = self._session.scalar(
            select(JobPositionRow).where(JobPositionRow.position_id == position_id)
        )
        return self._to_domain(row) if row else None

    def get_by_ids(self, position_ids: list[str]) -> list[JobPosition]:
        if not position_ids:
            return []
        rows = self._session.scalars(
            select(JobPositionRow).where(JobPositionRow.position_id.in_(position_ids))
        ).all()
        return [self._to_domain(r) for r in rows]

    def list_active(
        self,
        city: str | None = None,
        salary_min: int | None = None,
        salary_max: int | None = None,
        industry: str | None = None,
        keyword: str | None = None,
        experience: str | None = None,
        page: int = 1,
        page_size: int = 20,
        blacklist_companies: list[str] | None = None,
        blacklist_keywords: list[str] | None = None,
    ) -> tuple[list[JobPosition], int]:
        """多条件筛选：仅未过期职位；薪资为空的职位在薪资条件下放行；黑名单自动过滤。"""
        stmt = select(JobPositionRow).where(JobPositionRow.expired.is_(False))
        if city:
            stmt = stmt.where(JobPositionRow.city == city)
        if salary_min is not None:
            stmt = stmt.where(
                (JobPositionRow.salary_max.is_(None)) | (JobPositionRow.salary_max >= salary_min)
            )
        if salary_max is not None:
            stmt = stmt.where(
                (JobPositionRow.salary_min.is_(None)) | (JobPositionRow.salary_min <= salary_max)
            )
        if industry:
            stmt = stmt.where(JobPositionRow.industry == industry)
        if keyword:
            stmt = stmt.where(JobPositionRow.title.contains(keyword))
        if experience:
            stmt = stmt.where(JobPositionRow.experience_req.contains(experience))
        exclude_conditions = []
        if blacklist_companies:
            exclude_conditions.append(JobPositionRow.company.in_(blacklist_companies))
        if blacklist_keywords:
            exclude_conditions.extend(
                JobPositionRow.title.contains(k) for k in blacklist_keywords
            )
        if exclude_conditions:
            stmt = stmt.where(~or_(*exclude_conditions))
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(JobPositionRow.fetched_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_domain(r) for r in rows], int(total)

    def list_active_by_platforms(self, platform_ids: list[str]) -> list[JobPosition]:
        if not platform_ids:
            return []
        rows = self._session.scalars(
            select(JobPositionRow)
            .where(JobPositionRow.expired.is_(False), JobPositionRow.platform_id.in_(platform_ids))
            .order_by(JobPositionRow.fetched_at.desc())
        ).all()
        return [self._to_domain(r) for r in rows]

    def mark_expired(self, now: datetime) -> int:
        """软删除发布有效期已过的职位（expired 标记），保留投递记录关联。"""
        result = self._session.execute(
            update(JobPositionRow)
            .where(JobPositionRow.expired.is_(False), JobPositionRow.publish_expire_at < now)
            .values(expired=True)
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def count_all(self) -> int:
        return int(
            self._session.scalar(
                select(func.count()).select_from(JobPositionRow).where(JobPositionRow.expired.is_(False))
            )
            or 0
        )

    def delete_position(self, position_id: str) -> None:
        """演示模式清除专用：按职位 ID 物理删除（仅用于 demo_x_ 前缀演示职位）。"""
        self._session.execute(
            delete(JobPositionRow).where(JobPositionRow.position_id == position_id)
        )
        self._session.flush()


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: DeliveryTaskRow) -> DeliveryTask:
        return DeliveryTask(
            task_id=row.task_id,
            user_id=row.user_id,
            status=TaskStatus(row.status),
            created_at=row.created_at,
            resume_id=row.resume_id,
            resume_snapshot=ResumeSnapshot.from_dict(row.resume_snapshot),
            target_position_ids=list(row.target_position_ids or []),
            success_count=row.success_count,
            failed_count=row.failed_count,
            skipped_count=row.skipped_count,
        )

    def add(self, task: DeliveryTask) -> DeliveryTask:
        row = DeliveryTaskRow(
            task_id=task.task_id,
            user_id=task.user_id,
            status=task.status.value,
            created_at=task.created_at,
            resume_id=task.resume_id,
            resume_snapshot=task.resume_snapshot.to_dict(),
            target_position_ids=task.target_position_ids,
            success_count=task.success_count,
            failed_count=task.failed_count,
            skipped_count=task.skipped_count,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_domain(row)

    def get(self, task_id: str) -> DeliveryTask | None:
        row = self._session.get(DeliveryTaskRow, task_id)
        return self._to_domain(row) if row else None

    def list_by_resume(self, user_id: str, resume_id: str) -> list[DeliveryTask]:
        """删除保护：查询引用过指定简历档案的历史投递任务。"""
        rows = self._session.scalars(
            select(DeliveryTaskRow).where(
                DeliveryTaskRow.user_id == user_id,
                DeliveryTaskRow.resume_id == resume_id,
            )
        ).all()
        return [self._to_domain(r) for r in rows]

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        self._session.execute(
            update(DeliveryTaskRow).where(DeliveryTaskRow.task_id == task_id).values(status=status.value)
        )
        self._session.flush()

    def update_summary(self, task_id: str, success: int, failed: int, skipped: int) -> None:
        self._session.execute(
            update(DeliveryTaskRow)
            .where(DeliveryTaskRow.task_id == task_id)
            .values(success_count=success, failed_count=failed, skipped_count=skipped)
        )
        self._session.flush()

    def delete_task(self, task_id: str) -> None:
        """演示模式清除专用：按任务 ID 物理删除任务行（记录由 RecordRepository 单独清除）。"""
        self._session.execute(
            delete(DeliveryTaskRow).where(DeliveryTaskRow.task_id == task_id)
        )
        self._session.flush()


class RecordRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: DeliveryRecordRow) -> DeliveryRecord:
        return DeliveryRecord(
            record_id=row.record_id,
            user_id=row.user_id,
            task_id=row.task_id,
            position_id=row.position_id,
            platform_id=row.platform_id,
            status=DeliveryStatus(row.status),
            created_at=row.created_at,
            status_updated_at=row.status_updated_at,
            resume_snapshot=ResumeSnapshot.from_dict(row.resume_snapshot),
            delivered_at=row.delivered_at,
            failure_reason=row.failure_reason,
            platform_record_ref=row.platform_record_ref,
            idempotency_key=row.idempotency_key,
        )

    def add(self, record: DeliveryRecord) -> DeliveryRecord:
        row = DeliveryRecordRow(
            record_id=record.record_id,
            user_id=record.user_id,
            task_id=record.task_id,
            position_id=record.position_id,
            platform_id=record.platform_id,
            status=record.status.value,
            created_at=record.created_at,
            delivered_at=record.delivered_at,
            status_updated_at=record.status_updated_at,
            failure_reason=record.failure_reason,
            platform_record_ref=record.platform_record_ref,
            resume_snapshot=record.resume_snapshot.to_dict(),
            idempotency_key=record.idempotency_key,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_domain(row)

    def bulk_add(self, records: list[DeliveryRecord]) -> int:
        """任务确认时单事务批量落库为待投递（先落库后发送）。"""
        for r in records:
            self.add(r)
        return len(records)

    def get(self, record_id: str) -> DeliveryRecord | None:
        row = self._session.get(DeliveryRecordRow, record_id)
        return self._to_domain(row) if row else None

    def list_by_task(self, task_id: str) -> list[DeliveryRecord]:
        rows = self._session.scalars(
            select(DeliveryRecordRow)
            .where(DeliveryRecordRow.task_id == task_id)
            .order_by(DeliveryRecordRow.created_at)
        ).all()
        return [self._to_domain(r) for r in rows]

    def list_by_user(
        self,
        user_id: str,
        status: str | None = None,
        platform_id: str | None = None,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[DeliveryRecord], int]:
        """数据隔离：仅返回当前求职者本人的投递记录。"""
        stmt = select(DeliveryRecordRow).where(DeliveryRecordRow.user_id == user_id)
        if status:
            stmt = stmt.where(DeliveryRecordRow.status == status)
        if platform_id:
            stmt = stmt.where(DeliveryRecordRow.platform_id == platform_id)
        if since:
            stmt = stmt.where(DeliveryRecordRow.created_at >= since)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(DeliveryRecordRow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_domain(r) for r in rows], int(total)

    def find_recent_delivered(
        self, user_id: str, position_id: str, within_days: int = 30
    ) -> datetime | None:
        """30 天重复投递检查：索引点查最近一次成功投递时间。"""
        cutoff = datetime.now() - timedelta(days=within_days)
        delivered_at = self._session.scalar(
            select(func.max(DeliveryRecordRow.delivered_at)).where(
                DeliveryRecordRow.user_id == user_id,
                DeliveryRecordRow.position_id == position_id,
                DeliveryRecordRow.delivered_at.is_not(None),
                DeliveryRecordRow.delivered_at >= cutoff,
            )
        )
        return delivered_at

    def count_today(self, user_id: str, now: datetime | None = None) -> int:
        """按自然日统计当日已发起的投递数（每日上限口径）。"""
        now = now or datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(
            self._session.scalar(
                select(func.count()).select_from(DeliveryRecordRow).where(
                    DeliveryRecordRow.user_id == user_id,
                    DeliveryRecordRow.created_at >= day_start,
                )
            )
            or 0
        )

    def update_status(
        self,
        record_id: str,
        status: DeliveryStatus,
        status_updated_at: datetime,
        delivered_at: datetime | None = None,
        failure_reason: str | None = None,
        platform_record_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        values: dict = {
            "status": status.value,
            "status_updated_at": status_updated_at,
        }
        if delivered_at is not None:
            values["delivered_at"] = delivered_at
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        if platform_record_ref is not None:
            values["platform_record_ref"] = platform_record_ref
        if idempotency_key is not None:
            values["idempotency_key"] = idempotency_key
        self._session.execute(
            update(DeliveryRecordRow).where(DeliveryRecordRow.record_id == record_id).values(**values)
        )
        self._session.flush()

    def update_snapshot(self, record_id: str, snapshot: ResumeSnapshot) -> None:
        """删除保护：将档案快照固化到历史投递记录（防御性补固化）。"""
        self._session.execute(
            update(DeliveryRecordRow)
            .where(DeliveryRecordRow.record_id == record_id)
            .values(resume_snapshot=snapshot.to_dict())
        )
        self._session.flush()

    def delete_record(self, record_id: str) -> None:
        """演示模式清除专用：按记录 ID 物理删除（不入同步队列的演示数据）。"""
        self._session.execute(
            delete(DeliveryRecordRow).where(DeliveryRecordRow.record_id == record_id)
        )
        self._session.flush()

    def list_syncable(self, user_id: str) -> list[DeliveryRecord]:
        """待状态同步的记录：非终态且已有平台回执引用。"""
        syncable = {
            DeliveryStatus.delivered.value,
            DeliveryStatus.viewed.value,
            DeliveryStatus.interview_invited.value,
        }
        rows = self._session.scalars(
            select(DeliveryRecordRow).where(
                DeliveryRecordRow.user_id == user_id,
                DeliveryRecordRow.status.in_(syncable),
                DeliveryRecordRow.platform_record_ref.is_not(None),
            )
        ).all()
        return [self._to_domain(r) for r in rows]

    def statistics(self, user_id: str) -> dict:
        """投递统计：总数、各状态分布、各平台分布、近 7 天趋势。"""
        total = int(
            self._session.scalar(
                select(func.count()).select_from(DeliveryRecordRow).where(
                    DeliveryRecordRow.user_id == user_id
                )
            )
            or 0
        )
        status_rows = self._session.execute(
            select(DeliveryRecordRow.status, func.count())
            .where(DeliveryRecordRow.user_id == user_id)
            .group_by(DeliveryRecordRow.status)
        ).all()
        platform_rows = self._session.execute(
            select(DeliveryRecordRow.platform_id, func.count())
            .where(DeliveryRecordRow.user_id == user_id)
            .group_by(DeliveryRecordRow.platform_id)
        ).all()
        since = datetime.now() - timedelta(days=7)
        trend_rows = self._session.execute(
            select(
                func.date(DeliveryRecordRow.created_at).label("day"),
                func.count(),
            )
            .where(DeliveryRecordRow.user_id == user_id, DeliveryRecordRow.created_at >= since)
            .group_by("day")
            .order_by("day")
        ).all()
        return {
            "total": total,
            "status_distribution": {s: int(c) for s, c in status_rows},
            "platform_distribution": {p: int(c) for p, c in platform_rows},
            "recent_7_days": [
                {"date": str(d), "count": int(c)} for d, c in trend_rows
            ],
        }


class BlacklistRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: BlacklistEntryRow) -> BlacklistEntry:
        return BlacklistEntry(
            entry_id=row.entry_id,
            user_id=row.user_id,
            type=BlacklistType(row.type),
            content=row.content,
        )

    def add(self, entry: BlacklistEntry) -> BlacklistEntry:
        row = BlacklistEntryRow(
            entry_id=entry.entry_id,
            user_id=entry.user_id,
            type=entry.type.value,
            content=entry.content,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_domain(row)

    def list_by_user(self, user_id: str) -> list[BlacklistEntry]:
        rows = self._session.scalars(
            select(BlacklistEntryRow).where(BlacklistEntryRow.user_id == user_id)
        ).all()
        return [self._to_domain(r) for r in rows]

    def delete(self, user_id: str, entry_id: str) -> None:
        result = self._session.execute(
            delete(BlacklistEntryRow).where(
                BlacklistEntryRow.entry_id == entry_id,
                BlacklistEntryRow.user_id == user_id,
            )
        )
        self._session.flush()
        if result.rowcount == 0:
            raise LookupError(f"黑名单条目不存在: {entry_id}")


class AuthorizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, auth: PlatformAuthorization) -> PlatformAuthorization:
        row = self._session.get(PlatformAuthorizationRow, auth.platform_id)
        if row is None:
            row = PlatformAuthorizationRow(
                platform_id=auth.platform_id,
                user_id=auth.user_id,
                credential_cipher=auth.credential_cipher,
                status=auth.status.value,
                authorized_at=auth.authorized_at,
            )
            self._session.add(row)
        else:
            row.user_id = auth.user_id
            row.credential_cipher = auth.credential_cipher
            row.status = auth.status.value
            row.authorized_at = auth.authorized_at
        self._session.flush()
        return PlatformAuthorization(
            platform_id=row.platform_id,
            user_id=row.user_id,
            credential_cipher=row.credential_cipher,
            status=AuthStatus(row.status),
            authorized_at=row.authorized_at,
        )

    def get(self, platform_id: str) -> PlatformAuthorization | None:
        row = self._session.get(PlatformAuthorizationRow, platform_id)
        if row is None:
            return None
        return PlatformAuthorization(
            platform_id=row.platform_id,
            user_id=row.user_id,
            credential_cipher=row.credential_cipher,
            status=AuthStatus(row.status),
            authorized_at=row.authorized_at,
        )

    def delete(self, platform_id: str) -> None:
        row = self._session.get(PlatformAuthorizationRow, platform_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, action, detail: str, occurred_at: datetime) -> AuditLog:
        log = AuditLogRow(
            log_id=new_id("audit_"),
            action=action.value if hasattr(action, "value") else str(action),
            detail=detail,
            occurred_at=occurred_at,
        )
        self._session.add(log)
        self._session.flush()
        return AuditLog(
            log_id=log.log_id,
            action=log.action,
            detail=log.detail,
            occurred_at=log.occurred_at,
        )

class SettingRepository:
    """KV 设置存储：匹配阈值、每日投递上限等用户设置。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str, default=None):
        row = self._session.get(AppSettingRow, key)
        return row.value if row is not None else default

    def set(self, key: str, value) -> None:
        row = self._session.get(AppSettingRow, key)
        if row is None:
            row = AppSettingRow(key=key, value=value)
            self._session.add(row)
        else:
            row.value = value
        self._session.flush()
    def delete(self, key: str) -> None:
        """演示模式标记清除专用：按键删除 KV 行。"""
        row = self._session.get(AppSettingRow, key)
        if row is not None:
            self._session.delete(row)
            self._session.flush()