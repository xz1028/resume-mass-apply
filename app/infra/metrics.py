"""监控指标：投递尝试结果、平台接口失败率、投递记录状态分布（Prometheus 格式）。"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

DELIVERY_ATTEMPTS = Counter(
    "rma_delivery_attempts_total",
    "投递尝试总数",
    ["platform_id", "result"],
)

PLATFORM_FAILURES = Counter(
    "rma_platform_failures_total",
    "平台接口调用失败总数",
    ["platform_id"],
)

RECORD_STATUS_DISTRIBUTION = Gauge(
    "rma_delivery_records_status",
    "投递记录状态分布",
    ["status"],
)

CAPTCHA_CHALLENGES = Counter(
    "rma_captcha_challenges_total",
    "验证码挑战触发次数",
    ["platform_id", "stage"],
)

PLATFORM_RISK_EVENTS = Counter(
    "rma_platform_risk_events_total",
    "平台风控风险事件次数",
    ["platform_id", "event_type"],
)

AI_CALLS = Counter(
    "rma_ai_calls_total",
    "AI 模型调用次数",
    ["provider", "call_type", "result"],
)

AI_DEGRADES = Counter(
    "rma_ai_degrades_total",
    "AI 降级触发次数",
    ["reason"],
)

AI_CACHE_HITS = Counter(
    "rma_ai_cache_hits_total",
    "AI 缓存命中次数",
    ["kind"],
)


def inc_delivery_attempt(platform_id: str, result: str) -> None:
    """result: success | failed（每次投递尝试均计数）。"""
    DELIVERY_ATTEMPTS.labels(platform_id=platform_id, result=result).inc()


def inc_platform_failure(platform_id: str) -> None:
    PLATFORM_FAILURES.labels(platform_id=platform_id).inc()


def inc_captcha_challenge(platform_id: str, stage: str) -> None:
    CAPTCHA_CHALLENGES.labels(platform_id=platform_id, stage=stage).inc()


def inc_platform_risk_event(platform_id: str, event_type: str) -> None:
    PLATFORM_RISK_EVENTS.labels(platform_id=platform_id, event_type=event_type).inc()


def inc_ai_call(provider: str, call_type: str, result: str) -> None:
    """result: success | failed_retried | failed_degraded。"""
    AI_CALLS.labels(provider=provider, call_type=call_type, result=result).inc()


def inc_ai_degrade(reason: str) -> None:
    AI_DEGRADES.labels(reason=reason).inc()


def inc_ai_cache_hit(kind: str) -> None:
    """kind: match | greeting。"""
    AI_CACHE_HITS.labels(kind=kind).inc()


def set_status_distribution(distribution: dict[str, int]) -> None:
    for status, count in distribution.items():
        RECORD_STATUS_DISTRIBUTION.labels(status=status).set(count)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST