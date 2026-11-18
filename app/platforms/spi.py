"""平台适配器 SPI 契约：平台差异的唯一隔离点。

新增招聘平台 = 实现 PlatformAdapter 四方法 + 在注册表注册，无需修改任何上层代码。
适配器异常必须归类为三类统一异常之一。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import AuthStatus, ContactInfo, DeliveryStatus, JobIntention


class PlatformError(Exception):
    """平台适配器异常基类。"""


class PlatformAuthExpiredError(PlatformError):
    """平台授权已过期/凭证无效。"""


class PlatformRateLimitedError(PlatformError):
    """平台限流/风控拦截。"""


class PlatformUnavailableError(PlatformError):
    """平台接口不可用（网络超时/5xx 等）。"""


@dataclass
class RateLimitPolicy:
    max_per_hour: float = 30.0


@dataclass
class PositionDTO:
    position_id: str
    platform_id: str
    title: str
    company: str
    city: str
    salary_min: int | None = None
    salary_max: int | None = None
    industry: str = ""
    experience_req: str = ""
    publish_expire_at: datetime = field(default_factory=datetime.now)


@dataclass
class EncryptedResumeRef:
    """投递时传给平台的简历引用（解密后的原始文件内容）。"""

    name: str
    format: str
    content: bytes


@dataclass
class ApplyResult:
    success: bool
    platform_record_ref: str | None = None
    failure_reason: str | None = None
    receipt_time: datetime | None = None
    receipt_seq: int | None = None


@dataclass
class PlatformRecordRef:
    record_id: str
    platform_record_ref: str


@dataclass
class StatusReceipt:
    record_ref: str
    new_status: DeliveryStatus
    receipt_time: datetime
    receipt_seq: int


@runtime_checkable
class PlatformAdapter(Protocol):
    """平台适配器契约（design 8.1）。实现方无需显式继承即可通过类型检查。"""

    platform_id: str
    rate_limit: RateLimitPolicy

    def fetch_positions(self, intent: JobIntention, since: datetime) -> list[PositionDTO]: ...

    def submit_application(
        self,
        position: PositionDTO,
        resume_file: EncryptedResumeRef,
        contact: ContactInfo,
    ) -> ApplyResult: ...

    def fetch_application_status(
        self, record_refs: list[PlatformRecordRef]
    ) -> list[StatusReceipt]: ...

    def validate_authorization(self, credential: str) -> AuthStatus: ...