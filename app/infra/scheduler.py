"""定时调度：职位拉取、投递状态同步、过期职位清理、通知重发。

随应用启动而启动、随应用停止而停止；降级平台跳过拉取，恢复后自动补拉。
"""

from collections.abc import Callable
from datetime import datetime

from app.config import DEFAULT_USER_ID, settings
from app.infra.logging import get_logger

logger = get_logger("scheduler")

_scheduler = None


def _wrap_session_job(job: Callable, name: str) -> Callable[[], None]:
    """任务包装：独立会话 + 异常不外泄 + 结构化失败日志。"""

    def run() -> None:
        from app.infra.database import get_database

        session = get_database().session()
        try:
            job(session)
        except Exception:  # noqa: BLE001
            logger.exception("scheduled_job_failed", job=name)
        finally:
            session.close()

    return run


def start_scheduler():
    """启动三类周期任务 + 通知重发任务（幂等：重复调用返回已有实例）。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler

    from app.infra.notifier import get_notifier, resend_pending
    from app.platforms.registry import get_registry
    from app.services.job_service import JobService, make_recovery_fetcher
    from app.services.tracking_service import TrackingService

    registry = get_registry()
    registry.on_recovery(make_recovery_fetcher(registry))

    def fetch_job(session):
        result = JobService(session, registry).fetch_positions(DEFAULT_USER_ID)
        logger.info("scheduled_fetch_done", result=result)

    def sync_job(session):
        result = TrackingService(session, registry, get_notifier()).sync_status(DEFAULT_USER_ID)
        logger.info("scheduled_sync_done", result=result)

    def cleanup_job(session):
        count = JobService(session, registry).cleanup_expired()
        logger.info("scheduled_cleanup_done", expired=count)

    def notify_retry_job():
        resend_pending(get_notifier())

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _wrap_session_job(fetch_job, "job_fetch"),
        "interval",
        hours=settings.job_fetch_interval_hours,
        next_run_time=datetime.now(),  # 启动即拉一次：服务重启后已授权平台立即刷新职位池
        id="job_fetch",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _wrap_session_job(sync_job, "status_sync"),
        "interval",
        hours=settings.status_sync_interval_hours,
        id="status_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _wrap_session_job(cleanup_job, "expire_cleanup"),
        "interval",
        minutes=settings.expire_cleanup_interval_minutes,
        id="expire_cleanup",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        notify_retry_job,
        "interval",
        minutes=5,
        id="notify_retry",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "scheduler_started",
        fetch_hours=settings.job_fetch_interval_hours,
        sync_hours=settings.status_sync_interval_hours,
        cleanup_minutes=settings.expire_cleanup_interval_minutes,
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")