"""AI 领域枚举与 ORM 实体（5 张新表）。

继承既有 DeclarativeBase 元数据，database.create_all() 自动建表；
Key 列为 AES-256-GCM 密文（LargeBinary），永不存明文。
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.orm import Base


class ProviderKind(str, Enum):
    deepseek = "deepseek"
    qwen = "qwen"
    kimi = "kimi"
    zhipu = "zhipu"
    pangu = "pangu"
    openai_compat = "openai_compat"
    ollama = "ollama"


class TestStatus(str, Enum):
    success = "success"
    invalid_key = "invalid_key"
    insufficient_quota = "insufficient_quota"
    unreachable = "unreachable"
    none = "none"


class GreetingSource(str, Enum):
    ai = "ai"
    template = "template"
    edited = "edited"


class CallKind(str, Enum):
    match = "match"
    greeting = "greeting"
    test = "test"


class CallResult(str, Enum):
    success = "success"
    failed_retried = "failed_retried"
    failed_degraded = "failed_degraded"


class FailureKind(str, Enum):
    timeout = "timeout"
    rate_limited = "rate_limited"
    insufficient_quota = "insufficient_quota"
    invalid_key = "invalid_key"
    bad_format = "bad_format"
    unreachable = "unreachable"
    input_insufficient = "input_insufficient"


class BatchStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"


class AiModelConfigRow(Base):
    """模型服务配置：六服务商、单激活（部分唯一索引物理保证）、Key 密文。"""

    __tablename__ = "ai_model_configs"
    __table_args__ = (
        UniqueConstraint("name", name="ux_ai_config_name"),
        Index("ix_ai_configs_active", "is_active"),
    )

    config_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(128))
    api_key_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str] = mapped_column(String(24), default="none")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, default="")
    degraded_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    degraded_reason: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiMatchResultRow(Base):
    """AI 匹配结果缓存：复合键 (user_id, resume_hash, position_id, jd_hash)。"""

    __tablename__ = "ai_match_results"
    __table_args__ = (
        Index("ix_ai_match_position", "position_id", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    resume_hash: Mapped[str] = mapped_column(String(64))
    position_id: Mapped[str] = mapped_column(String(64))
    jd_hash: Mapped[str] = mapped_column(String(64))
    score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiGreetingRow(Base):
    """AI 招呼语：edited 独立列（不覆盖 AI 原版缓存）；最终版运行时合成（编辑优先）。"""

    __tablename__ = "ai_greetings"
    __table_args__ = (
        Index("ix_ai_greeting_task", "delivery_task_id"),
        Index("ix_ai_greeting_cache", "user_id", "resume_hash", "position_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    resume_hash: Mapped[str] = mapped_column(String(64))
    position_id: Mapped[str] = mapped_column(String(64))
    jd_hash: Mapped[str] = mapped_column(String(64))
    delivery_task_id: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="ai")
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiCallLogRow(Base):
    """AI 调用记录：只追加 + 环形淘汰；不含 Key 明文/简历明文/招呼语明文。"""

    __tablename__ = "ai_call_logs"
    __table_args__ = (Index("ix_ai_calls_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    call_type: Mapped[str] = mapped_column(String(16))
    result: Mapped[str] = mapped_column(String(24))
    failure_kind: Mapped[str] = mapped_column(String(32), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempted: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AiBatchTaskRow(Base):
    """AI 批任务：状态机 pending/running/completed/rejected/cancelled；LRU 32 条淘汰。"""

    __tablename__ = "ai_batch_tasks"

    task_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    kind: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[str] = mapped_column(String(64))
    top_n: Mapped[int] = mapped_column(Integer, default=50)
    delivery_task_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    degrade_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)