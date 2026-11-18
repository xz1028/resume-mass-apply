"""统一配置管理：全部配置项提供默认值，支持环境变量覆盖（前缀 RMA_）。"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RMA_", env_file=".env", extra="ignore")

    # 简历档案
    resume_allowed_formats: list[str] = Field(default=["pdf", "doc", "docx"])
    resume_max_size_mb: int = 20
    resume_storage_dir: Path = Path("data/resumes")

    # 定时任务周期（小时/分钟）
    job_fetch_interval_hours: int = 12
    status_sync_interval_hours: int = 6
    expire_cleanup_interval_minutes: int = 60

    # 批量投递
    daily_delivery_limit: int = 100
    retry_max_attempts: int = 2
    retry_backoff_seconds: list[int] = Field(default=[5, 15])
    platform_rate_limits_per_hour: dict[str, float] = Field(
        default_factory=lambda: {"mock_platform": 30.0}
    )

    # 智能匹配
    weight_skill: float = 0.5
    weight_experience: float = 0.2
    weight_city: float = 0.15
    weight_salary: float = 0.15
    matching_cache_ttl_seconds: int = 600
    auto_apply_threshold: int = 60

    # 安全
    secret_key_file: Path = Path("data/secret.key")

    # 存储
    database_url: str = "sqlite:///data/resume_mass_apply.db"

    # 通知
    notification_enabled: bool = True

    @field_validator("job_fetch_interval_hours")
    @classmethod
    def _validate_fetch_interval(cls, v: int) -> int:
        if not 1 <= v <= 24:
            raise ValueError("职位拉取周期必须在 1-24 小时之间")
        return v

    @field_validator("status_sync_interval_hours")
    @classmethod
    def _validate_sync_interval(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("状态同步周期必须在 1-12 小时之间")
        return v

    @field_validator("resume_max_size_mb")
    @classmethod
    def _validate_max_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("简历大小上限必须为正数")
        return v

    @field_validator("daily_delivery_limit")
    @classmethod
    def _validate_daily_limit(cls, v: int) -> int:
        if v < 1:
            raise ValueError("每日投递上限必须 >= 1")
        return v

    @field_validator("auto_apply_threshold")
    @classmethod
    def _validate_threshold(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("匹配阈值必须在 0-100 之间")
        return v


settings = Settings()
DEFAULT_USER_ID = "local_user"