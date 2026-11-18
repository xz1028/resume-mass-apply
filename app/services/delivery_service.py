"""批量投递服务：任务创建与前置校验、确认（先落库后发送）、异步执行引擎、取消、每日上限。

执行流水线（逐职位）：令牌桶限流 → 授权检查 → 黑名单/重复复核 → 有效期复核 →
发送投递请求 → 失败重试（最多 2 次，指数退避 5s/15s）→ 回执处理。
同平台串行、平台间并行；任何一次尝试（含失败）均有数据库记录与结构化日志。
"""

import asyncio
import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v1.errors import (
    DailyLimitReachedError,
    DuplicateDeliveryError,
    InvalidParamError,
    NotFoundError,
    TaskStateConflictError,
)
from app.config import settings
from app.domain.models import (
    AuthStatus,
    DeliveryRecord,
    DeliveryStatus,
    DeliveryTask,
    ResumeSnapshot,
    TaskStatus,
)
from app.infra.audit import AuditAction, record_audit
from app.infra.database import get_database
from app.infra.logging import get_logger
from app.infra.metrics import inc_delivery_attempt, inc_platform_failure
from app.infra.rate_limiter import RateLimiterRegistry, get_rate_limiters
from app.platforms.registry import AdapterRegistry, get_registry
from app.platforms.spi import (
    EncryptedResumeRef,
    PlatformAuthExpiredError,
    PlatformRateLimitedError,
    PositionDTO,
)
from app.repositories.repos import (
    AuthorizationRepository,
    BlacklistRepository,
    PositionRepository,
    RecordRepository,
    ResumeRepository,
    SeekerRepository,
    SettingRepository,
    TaskRepository,
    new_id,
)
from app.services.blacklist_service import BlacklistService
from app.services.matching_service import MatchingService
from app.services.resume_service import ResumeService

logger = get_logger("delivery_service")

DAILY_LIMIT_KEY = "daily_delivery_limit"
RATE_LIMIT_PAUSE_SECONDS = 60.0

_cancel_flags: set[str] = set()


def get_daily_limit(session: Session) -> int:
    return int(SettingRepository(session).get(DAILY_LIMIT_KEY, settings.daily_delivery_limit))


class DeliveryService:
    def __init__(
        self,
        session: Session,
        registry: AdapterRegistry,
        rate_limiters: RateLimiterRegistry,
        resume_service: ResumeService,
        matching_service: MatchingService,
    ) -> None:
        self._session = session
        self._registry = registry
        self._rate_limiters = rate_limiters
        self._resume_service = resume_service
        self._matching_service = matching_service

    # ---------- 任务创建与前置校验 ----------

    def create_task(
        self,
        user_id: str,
        position_ids: list[str] | None = None,
        filter_condition: dict | None = None,
    ) -> dict:
        """两种圈选方式统一归一化为目标职位集合，执行前置校验，生成待确认清单。"""
        resume = ResumeRepository(self._session).get_default(user_id)
        if resume is None:
            raise NotFoundError("请先上传简历并设置默认简历档案")

        positions = self._normalize_targets(user_id, position_ids, filter_condition)
        if not positions:
            raise InvalidParamError("目标职位为空，请检查职位列表或筛选条件")

        now = datetime.now()
        blacklist = BlacklistRepository(self._session).list_by_user(user_id)
        record_repo = RecordRepository(self._session)
        daily_limit = get_daily_limit(self._session)
        today_count = record_repo.count_today(user_id, now)

        valid: list = []
        rejected: list[dict] = []
        duplicate_blocked = False
        quota_exhausted = False
        for position in positions:
            if position.expired or position.publish_expire_at <= now:
                rejected.append(self._reject_item(position, "职位已过期"))
                continue
            if BlacklistService.is_blacklisted(position, blacklist):
                rejected.append(self._reject_item(position, "命中投递黑名单"))
                continue
            last = record_repo.find_recent_delivered(user_id, position.position_id)
            if last is not None:
                duplicate_blocked = True
                rejected.append(
                    self._reject_item(position, f"该职位已于 {last.month}月{last.day}日投递过")
                )
                continue
            if today_count + len(valid) >= daily_limit:
                quota_exhausted = True
                rejected.append(self._reject_item(position, "已达今日投递上限"))
                continue
            valid.append(position)

        if not valid:
            if quota_exhausted:
                raise DailyLimitReachedError("已达今日投递上限")
            if duplicate_blocked:
                raise DuplicateDeliveryError(
                    "全部职位被拦截：" + "；".join(r["reason"] for r in rejected)
                )
            raise InvalidParamError("目标职位均不可投递：" + "；".join(r["reason"] for r in rejected))

        _, content = self._resume_service.get_decrypted(user_id, resume.resume_id)
        snapshot = ResumeSnapshot(
            name=resume.name,
            format=resume.format.value,
            content_hash=hashlib.sha256(content).hexdigest(),
            created_at=resume.created_at,
        )
        task = TaskRepository(self._session).add(
            DeliveryTask(
                task_id=new_id("task_"),
                user_id=user_id,
                status=TaskStatus.pending_confirm,
                created_at=now,
                resume_id=resume.resume_id,
                resume_snapshot=snapshot,
                target_position_ids=[p.position_id for p in valid],
            )
        )
        record_audit(
            self._session,
            AuditAction.CREATE_DELIVERY_TASK,
            f"用户 {user_id} 创建投递任务 {task.task_id}，目标 {len(valid)} 个职位",
        )
        self._session.commit()
        logger.info("delivery_task_created", task_id=task.task_id, positions=len(valid))

        platform_dist: dict[str, int] = {}
        for p in valid:
            platform_dist[p.platform_id] = platform_dist.get(p.platform_id, 0) + 1
        return {
            "task": task,
            "checklist": {
                "position_count": len(valid),
                "platform_distribution": platform_dist,
                "resume_name": resume.name,
                "rejected": rejected,
            },
        }

    def _normalize_targets(
        self,
        user_id: str,
        position_ids: list[str] | None,
        filter_condition: dict | None,
    ) -> list:
        pos_repo = PositionRepository(self._session)
        if position_ids:
            positions = pos_repo.get_by_ids(position_ids)
            found = {p.position_id for p in positions}
            missing = [pid for pid in position_ids if pid not in found]
            if missing:
                raise NotFoundError(f"职位不存在: {', '.join(missing[:3])}")
            return positions
        if filter_condition:
            fc = filter_condition
            min_score = fc.get("min_match_score")
            if min_score is not None:
                scored = self._matching_service.scored_positions(user_id)
                candidates = [
                    item["position"]
                    for item in scored
                    if (item.get("effective_score") if item.get("effective_score") is not None else (item["match_score"] or 0)) >= min_score
                ]
            else:
                candidates, _total = pos_repo.list_active(page=1, page_size=100000)
            result = []
            for p in candidates:
                if fc.get("city") and p.city != fc["city"]:
                    continue
                if fc.get("industry") and p.industry != fc["industry"]:
                    continue
                if fc.get("keyword") and fc["keyword"] not in p.title:
                    continue
                if fc.get("experience") and fc["experience"] not in p.experience_req:
                    continue
                if fc.get("salary_min") is not None:
                    if p.salary_max is not None and p.salary_max < fc["salary_min"]:
                        continue
                if fc.get("salary_max") is not None:
                    if p.salary_min is not None and p.salary_min > fc["salary_max"]:
                        continue
                result.append(p)
            return result
        raise InvalidParamError("必须提供职位列表或筛选条件之一")

    @staticmethod
    def _reject_item(position, reason: str) -> dict:
        return {
            "position_id": position.position_id,
            "title": position.title,
            "reason": reason,
        }

    # ---------- 确认（先落库后发送） ----------

    def confirm_task(self, user_id: str, task_id: str) -> DeliveryTask:
        task_repo = TaskRepository(self._session)
        task = task_repo.get(task_id)
        if task is None or task.user_id != user_id:
            raise NotFoundError(f"投递任务不存在: {task_id}")
        if task.status != TaskStatus.pending_confirm:
            raise TaskStateConflictError(f"任务状态为 {task.status.value}，无法确认")

        profile = SeekerRepository(self._session).get_or_create(user_id)
        if not profile.contact.is_valid():
            raise InvalidParamError("请先在求职档案中配置有效联系方式（手机号或邮箱）")

        positions = PositionRepository(self._session).get_by_ids(task.target_position_ids)
        now = datetime.now()
        records = [
            DeliveryRecord(
                record_id=new_id("rec_"),
                user_id=user_id,
                task_id=task_id,
                position_id=p.position_id,
                platform_id=p.platform_id,
                status=DeliveryStatus.pending,
                created_at=now,
                status_updated_at=now,
                resume_snapshot=task.resume_snapshot,
            )
            for p in positions
        ]
        RecordRepository(self._session).bulk_add(records)
        task_repo.update_status(task_id, TaskStatus.executing)
        record_audit(
            self._session,
            AuditAction.CONFIRM_DELIVERY_TASK,
            f"用户 {user_id} 确认投递任务 {task_id}，落库 {len(records)} 条待投递记录",
        )
        self._session.commit()
        logger.info("task_confirmed", task_id=task_id, records=len(records))
        return task_repo.get(task_id)

    # ---------- 取消 ----------

    def cancel_task(self, user_id: str, task_id: str) -> dict:
        task_repo = TaskRepository(self._session)
        task = task_repo.get(task_id)
        if task is None or task.user_id != user_id:
            raise NotFoundError(f"投递任务不存在: {task_id}")
        if task.status not in (TaskStatus.pending_confirm, TaskStatus.executing):
            raise TaskStateConflictError(f"任务状态为 {task.status.value}，无法取消")
        if task.status == TaskStatus.pending_confirm:
            task_repo.update_status(task_id, TaskStatus.cancelled)
            self._session.commit()
            logger.info("task_cancelled", task_id=task_id, delivered=0,
                        remaining=len(task.target_position_ids))
            return {
                "task_id": task_id,
                "status": TaskStatus.cancelled.value,
                "delivered": 0,
                "remaining": len(task.target_position_ids),
            }
        _cancel_flags.add(task_id)
        stats = self._task_stats(task_id)
        logger.info("task_cancelling", task_id=task_id, **stats)
        return {"task_id": task_id, "status": "cancelling", **stats}

    # ---------- 查询 ----------

    def get_task(self, user_id: str, task_id: str) -> dict:
        task_repo = TaskRepository(self._session)
        task = task_repo.get(task_id)
        if task is None or task.user_id != user_id:
            raise NotFoundError(f"投递任务不存在: {task_id}")
        stats = self._task_stats(task_id)
        return {
            "task": task,
            "summary": {
                "success_count": stats["delivered"],
                "failed_count": stats["failed"],
                "skipped_count": task.skipped_count,
                "remaining": stats["remaining"],
            },
        }

    def _task_stats(self, task_id: str) -> dict:
        records = RecordRepository(self._session).list_by_task(task_id)
        return {
            "delivered": sum(1 for r in records if r.status == DeliveryStatus.delivered),
            "failed": sum(1 for r in records if r.status == DeliveryStatus.failed),
            "remaining": sum(1 for r in records if r.status == DeliveryStatus.pending),
        }

    # ---------- 执行引擎 ----------

    async def execute_task(self, task_id: str) -> None:
        """后台执行入口：按平台分组并行，平台内逐职位串行。"""
        task_repo = TaskRepository(self._session)
        task = task_repo.get(task_id)
        if task is None or task.status != TaskStatus.executing:
            return
        records = RecordRepository(self._session).list_by_task(task_id)
        by_platform: dict[str, list[DeliveryRecord]] = {}
        for r in records:
            by_platform.setdefault(r.platform_id, []).append(r)

        results = await asyncio.gather(
            *[
                self._execute_platform(task, platform_id, platform_records)
                for platform_id, platform_records in by_platform.items()
            ],
            return_exceptions=True,
        )
        skipped_total = 0
        for platform_id, result in zip(by_platform.keys(), results):
            if isinstance(result, Exception):
                logger.exception(
                    "platform_execution_error", task_id=task_id, platform_id=platform_id
                )
            elif isinstance(result, int):
                skipped_total += result

        self._session.expire_all()
        task = task_repo.get(task_id)
        stats = self._task_stats(task_id)
        task_repo.update_summary(
            task_id,
            success=stats["delivered"],
            failed=stats["failed"],
            skipped=skipped_total,
        )
        if task_id in _cancel_flags:
            task_repo.update_status(task_id, TaskStatus.cancelled)
            _cancel_flags.discard(task_id)
        elif task is not None and task.status == TaskStatus.executing:
            task_repo.update_status(task_id, TaskStatus.completed)
        self._session.commit()
        logger.info(
            "delivery_task_finished",
            task_id=task_id,
            success=stats["delivered"],
            failed=stats["failed"],
            skipped=skipped_total,
            remaining=stats["remaining"],
        )

    async def _execute_platform(
        self, task: DeliveryTask, platform_id: str, records: list[DeliveryRecord]
    ) -> int:
        """单平台执行流水线，返回跳过数量。"""
        record_repo = RecordRepository(self._session)
        pos_repo = PositionRepository(self._session)
        blacklist = BlacklistRepository(self._session).list_by_user(task.user_id)
        profile = SeekerRepository(self._session).get_or_create(task.user_id)

        adapter = self._registry.get(platform_id)
        if adapter is None:
            return self._log_skip(records, f"平台 {platform_id} 未注册")
        auth = AuthorizationRepository(self._session).get(platform_id)
        if auth is None or auth.status != AuthStatus.authorized:
            return self._log_skip(
                records,
                f"平台 {platform_id} 授权已过期，本次共跳过 {len(records)} 个职位，请重新授权",
            )

        resume = ResumeRepository(self._session).get(task.user_id, task.resume_id)
        if resume is None:
            return self._log_skip(records, f"投递简历档案不存在: {task.resume_id}")
        _, content = self._resume_service.get_decrypted(task.user_id, task.resume_id)
        resume_ref = EncryptedResumeRef(
            name=task.resume_snapshot.name,
            format=task.resume_snapshot.format,
            content=content,
        )

        skipped = 0
        for index, record in enumerate(records):
            if task.task_id in _cancel_flags:
                break
            position = pos_repo.get(record.position_id)
            if position is None:
                skipped += 1
                continue
            if BlacklistService.is_blacklisted(position, blacklist):
                skipped += 1
                logger.info("delivery_skip_blacklist", position_id=position.position_id)
                continue
            if record_repo.find_recent_delivered(task.user_id, position.position_id) is not None:
                skipped += 1
                logger.info("delivery_skip_duplicate", position_id=position.position_id)
                continue
            if position.publish_expire_at <= datetime.now():
                record_repo.update_status(record.record_id, DeliveryStatus.expired, datetime.now())
                self._session.commit()
                continue
            wait = self._rate_limiters.wait_time(platform_id)
            if wait > 0:
                logger.info(
                    "rate_limit_wait",
                    platform_id=platform_id,
                    wait_seconds=round(wait, 2),
                )
                await asyncio.sleep(wait)
            try:
                await self._submit_with_retry(
                    task, platform_id, adapter, position, resume_ref, profile.contact, record
                )
            except PlatformAuthExpiredError:
                rest = records[index:]
                skipped += len(rest)
                logger.warning(
                    "platform_auth_expired_skip",
                    platform_id=platform_id,
                    task_id=task.task_id,
                    skipped=len(rest),
                    message=f"平台 {platform_id} 授权已过期，本次共跳过 {len(rest)} 个职位，请重新授权",
                )
                break
        return skipped

    async def _submit_with_retry(
        self,
        task: DeliveryTask,
        platform_id: str,
        adapter,
        position,
        resume_ref: EncryptedResumeRef,
        contact,
        record: DeliveryRecord,
    ) -> None:
        """发送投递请求：可重试错误最多重试 2 次（指数退避 5s/15s）。"""
        record_repo = RecordRepository(self._session)
        pos_dto = PositionDTO(
            position_id=position.position_id,
            platform_id=position.platform_id,
            title=position.title,
            company=position.company,
            city=position.city,
            salary_min=position.salary_min,
            salary_max=position.salary_max,
            industry=position.industry,
            experience_req=position.experience_req,
            publish_expire_at=position.publish_expire_at,
        )
        attempts = 1 + settings.retry_max_attempts
        backoffs = settings.retry_backoff_seconds or [5, 15]
        final_greeting = self._read_final_greeting(task.task_id, position.position_id)
        for attempt in range(attempts):
            if task.task_id in _cancel_flags:
                return
            try:
                result = await asyncio.to_thread(
                    adapter.submit_application, pos_dto, resume_ref, contact, final_greeting
                )
            except PlatformAuthExpiredError:
                raise
            except PlatformRateLimitedError as exc:
                logger.warning(
                    "delivery_rate_limited",
                    platform_id=platform_id,
                    position_id=position.position_id,
                    reason=str(exc),
                    message=f"平台 {platform_id} 触发投递限制，已自动放缓投递速度",
                )
                await asyncio.sleep(RATE_LIMIT_PAUSE_SECONDS)
                continue
            except Exception as exc:  # noqa: BLE001
                inc_platform_failure(platform_id)
                inc_delivery_attempt(platform_id, "failed")
                logger.warning(
                    "delivery_attempt",
                    platform_id=platform_id,
                    position_id=position.position_id,
                    result="failed",
                    reason=str(exc),
                    attempt=attempt + 1,
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(backoffs[min(attempt, len(backoffs) - 1)])
                    continue
                record_repo.update_status(
                    record.record_id,
                    DeliveryStatus.failed,
                    datetime.now(),
                    failure_reason=str(exc),
                )
                self._session.commit()
                return
            now = datetime.now()
            if result.success is False:
                record_repo.update_status(
                    record.record_id,
                    DeliveryStatus.failed,
                    now,
                    failure_reason=result.failure_reason or "平台返回投递失败",
                )
                self._session.commit()
                inc_delivery_attempt(platform_id, "failed")
                logger.warning(
                    "delivery_attempt",
                    platform_id=platform_id,
                    position_id=position.position_id,
                    result="failed",
                    reason=result.failure_reason or "平台返回投递失败",
                )
                return
            record_repo.update_status(
                record.record_id,
                DeliveryStatus.delivered,
                now,
                delivered_at=now,
                platform_record_ref=result.platform_record_ref,
            )
            self._session.commit()
            inc_delivery_attempt(platform_id, "success")
            logger.info(
                "delivery_attempt",
                platform_id=platform_id,
                position_id=position.position_id,
                result="success",
                reason="",
            )
            return

    @staticmethod
    def _read_final_greeting(task_id: str, position_id: str) -> str | None:
        """读取该职位最终招呼语（编辑版 > AI 生成版 > None）。

        独立会话毫秒级同步读取；AI 组件不可用/异常时返回 None，
        适配器内部固定模板兜底（与既有行为一致，不改投递成功/失败判定）。
        """
        try:
            session = get_database().session()
            try:
                from app.ai.greeting.service import GreetingService

                return GreetingService(session).final_greeting(task_id, position_id)
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _log_skip(records: list[DeliveryRecord], message: str) -> int:
        logger.warning("delivery_skip", skipped=len(records), message=message)
        return len(records)


def build_delivery_service(session: Session) -> DeliveryService:
    """统一服务工厂：API 依赖注入与后台任务共用。"""
    resume_service = ResumeService(session, get_crypto_safe(), settings.resume_storage_dir)
    matching_service = MatchingService(session, resume_service)
    return DeliveryService(
        session,
        get_registry(),
        get_rate_limiters(),
        resume_service,
        matching_service,
    )


def get_crypto_safe():
    from app.infra.crypto import get_crypto

    return get_crypto()


async def run_delivery_task(task_id: str) -> None:
    """后台执行投递任务：独立会话，任何异常不外泄。"""
    session = get_database().session()
    try:
        service = build_delivery_service(session)
        await service.execute_task(task_id)
    except Exception:  # noqa: BLE001
        logger.exception("delivery_task_crashed", task_id=task_id)
    finally:
        session.close()