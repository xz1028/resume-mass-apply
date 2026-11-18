"""领域实体与值对象：命名与 spec 第 2 章领域术语一一对应。

值对象（ContactInfo/JobIntention/ResumeSnapshot）以 JSON 列内嵌属主实体持久化。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DeliveryStatus(str, Enum):
    pending = "pending"                    # 待投递
    delivered = "delivered"                # 已投递
    viewed = "viewed"                      # 已查看
    interview_invited = "interview_invited"  # 面试邀请
    rejected = "rejected"                  # 不合适
    failed = "failed"                      # 投递失败
    expired = "expired"                    # 已过期


class TaskStatus(str, Enum):
    pending_confirm = "pending_confirm"
    executing = "executing"
    completed = "completed"
    cancelled = "cancelled"


class BlacklistType(str, Enum):
    company = "company"
    keyword = "keyword"


class AuthStatus(str, Enum):
    authorized = "authorized"
    expired = "expired"
    unauthorized = "unauthorized"


class ResumeFormat(str, Enum):
    pdf = "pdf"
    doc = "doc"
    docx = "docx"


class DomainConstraintError(Exception):
    """领域约束违反的基类。"""


class DuplicateResumeNameError(DomainConstraintError):
    """同一求职者下简历档案重名（错误码 40004）。"""


class MultipleDefaultResumeError(DomainConstraintError):
    """同一求职者下出现多于一个默认简历档案。"""


@dataclass
class ContactInfo:
    phone: str | None = None
    email: str | None = None

    def is_valid(self) -> bool:
        import re

        phone_ok = self.phone is not None and re.fullmatch(r"1[3-9]\d{9}", self.phone) is not None
        email_ok = self.email is not None and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.email) is not None
        return phone_ok or email_ok


@dataclass
class JobIntention:
    city: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    industry: str | None = None

    def to_dict(self) -> dict:
        return {"city": self.city, "salary_min": self.salary_min,
                "salary_max": self.salary_max, "industry": self.industry}

    @classmethod
    def from_dict(cls, data: dict | None) -> "JobIntention":
        data = data or {}
        return cls(
            city=data.get("city"),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            industry=data.get("industry"),
        )


@dataclass
class ResumeSnapshot:
    """简历快照值对象：档案删除后历史投递记录仍可查看（删除保护）。"""

    name: str
    format: str
    content_hash: str
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "format": self.format,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResumeSnapshot":
        return cls(
            name=data["name"],
            format=data["format"],
            content_hash=data["content_hash"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass
class JobSeekerProfile:
    user_id: str
    contact: ContactInfo = field(default_factory=ContactInfo)
    intention: JobIntention = field(default_factory=JobIntention)


@dataclass
class ResumeProfile:
    resume_id: str
    user_id: str
    name: str
    format: ResumeFormat
    size_bytes: int
    is_default: bool
    created_at: datetime
    storage_ref: str


@dataclass
class JobPosition:
    position_id: str
    platform_id: str
    title: str
    company: str
    city: str
    salary_min: int | None
    salary_max: int | None
    industry: str
    experience_req: str
    publish_expire_at: datetime
    fetched_at: datetime
    expired: bool = False
    jd_text: str | None = None
    jd_fetched_at: datetime | None = None


@dataclass
class DeliveryTask:
    task_id: str
    user_id: str
    status: TaskStatus
    created_at: datetime
    resume_id: str
    resume_snapshot: ResumeSnapshot
    target_position_ids: list[str] = field(default_factory=list)
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


@dataclass
class DeliveryRecord:
    record_id: str
    user_id: str
    task_id: str
    position_id: str
    platform_id: str
    status: DeliveryStatus
    created_at: datetime
    status_updated_at: datetime
    resume_snapshot: ResumeSnapshot
    delivered_at: datetime | None = None
    failure_reason: str | None = None
    platform_record_ref: str | None = None
    idempotency_key: str | None = None


@dataclass
class BlacklistEntry:
    entry_id: str
    user_id: str
    type: BlacklistType
    content: str


@dataclass
class PlatformAuthorization:
    platform_id: str
    user_id: str
    credential_cipher: bytes
    status: AuthStatus
    authorized_at: datetime


@dataclass
class AuditLog:
    log_id: str
    action: str
    detail: str
    occurred_at: datetime