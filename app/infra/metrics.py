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


def inc_delivery_attempt(platform_id: str, result: str) -> None:
    """result: success | failed（每次投递尝试均计数）。"""
    DELIVERY_ATTEMPTS.labels(platform_id=platform_id, result=result).inc()


def inc_platform_failure(platform_id: str) -> None:
    PLATFORM_FAILURES.labels(platform_id=platform_id).inc()


def set_status_distribution(distribution: dict[str, int]) -> None:
    for status, count in distribution.items():
        RECORD_STATUS_DISTRIBUTION.labels(status=status).set(count)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST