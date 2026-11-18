"""启动装配与预置数据：三平台接入配置预置 + 启用平台注册 + 归档清理 + 崩溃恢复幂等重建。"""

from app.config import settings
from app.infra.audit import AuditAction  # noqa: F401
from app.infra.logging import get_logger
from app.platforms.registry import AdapterRegistry
from app.real_platform.access.repositories import (
    AccessConfigRepository,
    CaptchaChallengeRepository,
    RiskEventRepository,
)

logger = get_logger("bootstrap")

BOSS_ACCESS_NOTE = (
    "接入方式：浏览器自动化（本机 Chrome/Edge 受控操作）。"
    "官方未向个人开发者开放职位/投递 API，此方式为当前唯一可行通道，"
    "存在账号被平台限制或封禁的风险，请谨慎使用。"
)
ZHILIAN_ACCESS_NOTE = BOSS_ACCESS_NOTE
JOB51_ACCESS_NOTE = BOSS_ACCESS_NOTE

P1_PLACEHOLDER_NOTE = "P1 扩展平台：适配器规划中，接入方式待评估。"

PRESET_PLATFORMS = [
    ("boss_zhipin", "BOSS直聘", "browser_automation", "P0", BOSS_ACCESS_NOTE),
    ("zhilian", "智联招聘", "browser_automation", "P0", ZHILIAN_ACCESS_NOTE),
    ("job51", "前程无忧", "browser_automation", "P0", JOB51_ACCESS_NOTE),
]


def bootstrap_real_platforms(session, registry: AdapterRegistry) -> None:
    """启动装配：预置配置 → 注册启用平台 → 限流注入 → 惰性归档清理。幂等可重入。"""
    config_repo = AccessConfigRepository(session)

    for platform_id, name, access_mode, priority, note in PRESET_PLATFORMS:
        config_repo.ensure_preset(
            platform_id=platform_id,
            name=name,
            access_mode=access_mode,
            priority=priority,
            access_mode_note=note,
            delivery_rate_per_hour=settings.real_platform_default_rate_per_hour,
            fetch_interval_hours=settings.real_platform_fetch_interval_floor_hours,
        )

    from app.infra.rate_limiter import get_rate_limiters

    for row in config_repo.list_all():
        if row.priority == "P0" and row.enabled:
            adapter = _build_adapter(row.platform_id, row.delivery_rate_per_hour)
            if adapter is None:
                continue
            existing = registry.get(row.platform_id)
            if existing is None:
                registry.register(adapter, name=row.name)
            elif existing is not adapter:
                logger.warning(
                    "platform_id_conflict",
                    platform_id=row.platform_id,
                    reason="启动装配检测到标识冲突，跳过重复注册",
                )
                continue
            get_rate_limiters().set_policy(row.platform_id, row.delivery_rate_per_hour)
            logger.info(
                "real_platform_registered",
                platform_id=row.platform_id,
                rate_per_hour=row.delivery_rate_per_hour,
            )

    # 惰性归档清理：终态挑战/已告知事件 30 天归档
    captcha_cleaned = CaptchaChallengeRepository(session).archive_terminal()
    risk_cleaned = RiskEventRepository(session).archive_terminal()
    session.commit()
    if captcha_cleaned or risk_cleaned:
        logger.info(
            "access_archive_cleaned", captcha=captcha_cleaned, risk_events=risk_cleaned
        )

    # 启动浏览器会话巡检（凭证撤销兜底）与降级恢复探测器
    from app.real_platform.access.service import PlatformAccessService

    probe = _credential_probe_builder(session, registry)
    from app.real_platform.browser.session_manager import get_session_manager

    manager = get_session_manager()
    manager.bind_credential_probe(probe)
    manager.start_patrol()

    from app.real_platform.access.recovery_probe import get_recovery_probe

    get_recovery_probe(registry).start()


def _credential_probe_builder(session, registry):
    """巡检探针：platform_id → 凭证是否仍存在（撤销授权兜底自动关闭会话）。"""

    def probe(platform_id: str) -> bool:
        from app.repositories.repos import AuthorizationRepository

        probe_session = _new_session()
        try:
            return AuthorizationRepository(probe_session).get(platform_id) is not None
        finally:
            probe_session.close()

    return probe


def _new_session():
    from app.infra.database import get_database

    return get_database().session()


def _build_adapter(platform_id: str, rate_per_hour: float):
    factory = _adapter_factory()
    cls = factory.get(platform_id)
    if cls is None:
        return None
    return cls(rate_per_hour=rate_per_hour)


def _adapter_factory() -> dict:
    from app.real_platform.adapters.boss_zhipin import BossZhipinAdapter
    from app.real_platform.adapters.job51 import Job51Adapter
    from app.real_platform.adapters.zhilian import ZhilianAdapter

    return {
        "boss_zhipin": BossZhipinAdapter,
        "zhilian": ZhilianAdapter,
        "job51": Job51Adapter,
    }


def shutdown_real_platforms() -> None:
    """应用停止时：停止巡检/探测器/全部浏览器会话。"""
    from app.real_platform.access.recovery_probe import reset_recovery_probe_singleton
    from app.real_platform.browser.session_manager import (
        get_session_manager,
        reset_session_manager_singleton,
    )

    try:
        reset_recovery_probe_singleton()
        get_session_manager().shutdown()
        reset_session_manager_singleton()
    except Exception:  # noqa: BLE001
        logger.exception("real_platform_shutdown_failed")