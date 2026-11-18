"""风控信号检测与风险事件落库：按信号词典归类三类统一异常。

信号分类（设计 2.1.3(7)）：
- 限流关键词 / HTTP 429 → PlatformRateLimitedError → rate_limited 事件
- 账号受限关键词 → PlatformRateLimitedError → account_restricted 事件
- 封禁关键词 / HTTP 403 → PlatformAuthExpiredError → account_banned 事件（停止交互+凭证过期）
- 接口结构变更（容器不可解析）→ PlatformUnavailableError → interface_changed 事件
- 登录态失效/重定向登录页 → PlatformAuthExpiredError（无风险事件，授权过期既有路径）
"""

from app.infra.logging import get_logger
from app.infra.metrics import inc_platform_risk_event
from app.platforms.spi import (
    PlatformAuthExpiredError,
    PlatformRateLimitedError,
    PlatformUnavailableError,
)
from app.real_platform.access.repositories import RiskEventRepository

logger = get_logger("risk_detector")

RATE_LIMIT_KEYWORDS = ("访问过于频繁", "操作太频繁", "请求过于频繁", "稍后再试", "frequent")
ACCOUNT_RESTRICTED_KEYWORDS = ("账号异常", "账号受限", "功能受限", "异常行为", "security")
ACCOUNT_BANNED_KEYWORDS = ("账号已被封禁", "账号封禁", "永久封禁", "banned", "违规封禁")
LOGIN_REDIRECT_MARKS = ("登录", "login", "扫码登录")


def classify_text_signal(text: str, login_url_hint: bool = False):
    """页面文案信号 → (异常构造器, 事件类型) 或 None。"""
    if not text:
        return None
    lowered = text.lower()
    for kw in ACCOUNT_BANNED_KEYWORDS:
        if kw in lowered:
            return PlatformAuthExpiredError, "account_banned"
    for kw in ACCOUNT_RESTRICTED_KEYWORDS:
        if kw in lowered:
            return PlatformRateLimitedError, "account_restricted"
    for kw in RATE_LIMIT_KEYWORDS:
        if kw in lowered:
            return PlatformRateLimitedError, "rate_limited"
    if login_url_hint:
        return PlatformAuthExpiredError, None
    return None


def record_risk_event(session_factory, platform_id: str, event_type: str, detail: str = "") -> None:
    """风险事件落库（预置处置建议，notified=False 待前端告知）+ 指标计数。"""
    session = session_factory()
    try:
        RiskEventRepository(session).append(platform_id, event_type, detail)
        session.commit()
    finally:
        session.close()
    inc_platform_risk_event(platform_id=platform_id, event_type=event_type)


def raise_for_http_status(status: int, platform_id: str) -> None:
    """HTTP 状态信号：429→限流异常；403→封禁类（授权过期语义，停止交互）。"""
    if status == 429:
        raise PlatformRateLimitedError(f"平台 {platform_id} 返回 429，触发限流")
    if status == 403:
        raise PlatformAuthExpiredError(f"平台 {platform_id} 返回 403，账号可能受限或封禁")


def raise_for_page_text(text: str, platform_id: str, session_factory, login_url_hint: bool = False) -> None:
    """页面文案信号归类：抛三类统一异常并落风险事件。"""
    signal = classify_text_signal(text, login_url_hint)
    if signal is None:
        return
    exc_cls, event_type = signal
    if event_type is not None:
        record_risk_event(session_factory, platform_id, event_type, detail=text[:80])
    raise exc_cls(f"平台 {platform_id} 检测到风控信号")


def raise_for_parse_failure(platform_id: str, session_factory, parse_stage: str) -> None:
    """结构解析失败（页面变更特征）→ 平台不可用 + interface_changed 事件。"""
    record_risk_event(session_factory, platform_id, "interface_changed", detail=parse_stage)
    raise PlatformUnavailableError(f"平台 {platform_id} 页面结构变更，解析失败（{parse_stage}）")