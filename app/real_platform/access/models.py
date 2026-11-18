"""接入治理数据模型：三张新表（接入配置/验证码挑战/风险事件）。

继承既有 DeclarativeBase 元数据，database.create_all() 自动建表；
表内不落任何凭证/验证码内容字段（数据约束 spec 6.1-6.4）。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.orm import Base


class PlatformAccessConfigRow(Base):
    """平台接入配置：接入方式/优先级/启用状态/限流策略/风险确认标记。"""

    __tablename__ = "platform_access_configs"

    platform_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    access_mode: Mapped[str] = mapped_column(String(32), default="browser_automation")
    priority: Mapped[str] = mapped_column(String(8), default="P0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_rate_per_hour: Mapped[float] = mapped_column(Float, default=20.0)
    fetch_interval_hours: Mapped[int] = mapped_column(Integer, default=12)
    access_mode_note: Mapped[str] = mapped_column(Text, default="")


class CaptchaChallengeRow(Base):
    """验证码挑战：pending 期间门闸生效；表内不含验证码内容。"""

    __tablename__ = "captcha_challenges"


    challenge_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    platform_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlatformRiskEventRow(Base):
    """平台风险事件：按类型预置处置建议，读取即置 notified。"""

    __tablename__ = "platform_risk_events"

    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    platform_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    advice: Mapped[str] = mapped_column(Text, default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)