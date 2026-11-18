"""结构化日志：structlog JSON 输出 + 凭证类字段自动脱敏。"""

import logging
import re

import structlog

SENSITIVE_KEY_PATTERN = re.compile(r"(credential|token|password|secret|cipher|contact|phone|email)", re.IGNORECASE)
REDACTED = "***"


def _redact(value):
    if isinstance(value, dict):
        return {k: (REDACTED if SENSITIVE_KEY_PATTERN.search(str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _redact_processor(logger, method: str, event_dict: dict) -> dict:
    return {k: (REDACTED if SENSITIVE_KEY_PATTERN.search(str(k)) else _redact(v)) for k, v in event_dict.items()}


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)