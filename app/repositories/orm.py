"""SQLAlchemy ORM 表定义。

关键索引：
- 职位（platform_id, position_id）唯一索引：去重 upsert；
- 职位（city, expired）二级索引：城市筛选；
- 投递记录（user_id, position_id, delivered_at）索引：30 天重复投递点查；
- 简历（user_id, name）唯一索引：档案唯一命名。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeekerProfileRow(Base):
    __tablename__ = "seeker_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    contact: Mapped[dict] = mapped_column(JSON, default=dict)
    intention: Mapped[dict] = mapped_column(JSON, default=dict)


class ResumeProfileRow(Base):
    __tablename__ = "resume_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="ux_resume_user_name"),
        Index("ix_resume_user_created", "user_id", "created_at"),
    )

    resume_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    storage_ref: Mapped[str] = mapped_column(String(512))


class JobPositionRow(Base):
    __tablename__ = "job_positions"
    __table_args__ = (
        UniqueConstraint("platform_id", "position_id", name="ux_position_platform"),
        Index("ix_position_city_expired", "city", "expired"),
        Index("ix_position_expired_fetched", "expired", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[str] = mapped_column(String(64))
    position_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(64))
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    industry: Mapped[str] = mapped_column(String(128), default="")
    experience_req: Mapped[str] = mapped_column(String(64), default="")
    publish_expire_at: Mapped[datetime] = mapped_column(DateTime)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    expired: Mapped[bool] = mapped_column(Boolean, default=False)


class DeliveryTaskRow(Base):
    __tablename__ = "delivery_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resume_id: Mapped[str] = mapped_column(String(64))
    resume_snapshot: Mapped[dict] = mapped_column(JSON)
    target_position_ids: Mapped[list] = mapped_column(JSON, default=list)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)


class DeliveryRecordRow(Base):
    __tablename__ = "delivery_records"
    __table_args__ = (
        Index(
            "ix_record_user_position_delivered",
            "user_id",
            "position_id",
            "delivered_at",
        ),
        Index("ix_record_user_created", "user_id", "created_at"),
        Index("ix_record_task", "task_id"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64))
    position_id: Mapped[str] = mapped_column(String(64))
    platform_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_record_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resume_snapshot: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class BlacklistEntryRow(Base):
    __tablename__ = "blacklist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "content", name="ux_blacklist_entry"),
    )

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(255))


class PlatformAuthorizationRow(Base):
    __tablename__ = "platform_authorizations"

    platform_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    credential_cipher: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16))
    authorized_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)

class AppSettingRow(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)