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

    # 真实招聘平台接入（浏览器自动化）
    browser_channel_order: list[str] = Field(default_factory=lambda: ["msedge", "chrome"])
    captcha_wait_timeout_seconds: int = 600
    browser_idle_recycle_seconds: int = 600
    browser_patrol_interval_seconds: int = 60
    browser_command_throttle_seconds: tuple[int, int] = (2, 5)
    delivery_hard_limit_per_hour: int = 30
    real_platform_default_rate_per_hour: float = 20.0
    real_platform_fetch_interval_floor_hours: int = 12
    pending_events_poll_seconds: int = 30
    recovery_probe_interval_seconds: int = 3600
    browser_profiles_dir: Path = Path("data/browser_profiles")

    # AI 智能匹配与招呼语
    ai_match_cache_ttl_seconds: int = 24 * 3600
    ai_greeting_cache_ttl_seconds: int = 24 * 3600
    ai_concurrency: int = 3
    ai_cache_capacity: int = 2000
    ai_call_log_capacity: int = 2000
    ai_batch_task_retention: int = 32
    ai_input_insufficient_threshold_chars: int = 200
    ai_config_cooldown_seconds: int = 600
    ai_matching_task_idempotent_window_seconds: int = 60

    # 演示模式一键开箱（默认 off：源码/测试形态演示注入永不触发；
    # 仅绿色包启动器注入 RMA_DEMO_MODE=auto 时启用——142 项既有测试零影响红线）
    demo_mode: str = "off"

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