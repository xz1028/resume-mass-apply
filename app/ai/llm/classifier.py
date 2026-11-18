"""失败原因分类映射：异常 → 七类失败枚举（五类异常场景全覆盖）。

401/403→invalid_key；429→rate_limited；402/余额文案→insufficient_quota；
连接拒绝/DNS→unreachable（Ollama 连接失败附启动提示）；超时→timeout；
解析异常→bad_format。
"""

from app.ai.models import FailureKind

QUOTA_TEXT_MARKS = ("insufficient", "quota", "balance", "余额", "欠费", "充值")


def classify_status(status: int, body_text: str = "") -> FailureKind:
    if status in (401, 403):
        return FailureKind.invalid_key
    if status == 429:
        return FailureKind.rate_limited
    if status == 402:
        return FailureKind.insufficient_quota
    lowered = (body_text or "").lower()
    for mark in QUOTA_TEXT_MARKS:
        if mark in lowered:
            return FailureKind.insufficient_quota
    if status >= 500:
        return FailureKind.unreachable
    return FailureKind.bad_format


def classify_exception(exc: Exception) -> FailureKind:
    name = type(exc).__name__
    text = str(exc).lower()
    if name == "TimeoutException" or "timed out" in text or "timeout" in text:
        return FailureKind.timeout
    if name in ("ConnectError", "ConnectTimeout", "DNSFailure") or "connect" in text or "connection refused" in text:
        return FailureKind.unreachable
    if name == "BadJSONResponse" or "json" in text and "decode" in text:
        return FailureKind.bad_format
    return FailureKind.unreachable


def failure_message(kind: FailureKind, provider: str) -> str:
    if kind == FailureKind.timeout:
        return "模型服务响应超时"
    if kind == FailureKind.rate_limited:
        return "模型服务限流，稍后自动重试或降级"
    if kind == FailureKind.insufficient_quota:
        return "模型服务余额不足，请充值后重试"
    if kind == FailureKind.invalid_key:
        return "API Key 无效，请检查后重试"
    if kind == FailureKind.bad_format:
        return "模型返回格式异常"
    if kind == FailureKind.unreachable:
        if provider == "ollama":
            return "本地模型服务不可达，请确认 Ollama 已启动"
        return "模型服务不可达，请检查网络或接口地址"
    return "输入内容不足，已使用规则评分"


def is_retryable(kind: FailureKind) -> bool:
    """仅可重试类：超时/网络/5xx（unreachable）/限流；其余直接降级。"""
    return kind in (
        FailureKind.timeout,
        FailureKind.rate_limited,
        FailureKind.unreachable,
    )