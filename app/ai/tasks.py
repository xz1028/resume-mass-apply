"""AI 后台任务编排器：匹配/招呼语批任务生命周期、幂等发起、rejected 语义、增量查询。

设计（tasks 组 9）：
- asyncio.create_task + 进程内任务注册表（弱引用语义：页面切换不中断，进程退出终止）
- 任务状态落 ai_batch_tasks 表；重启后进行中任务终止（降级为规则评分语义）
- 幂等：60 秒内同 user_id+top_n 的未完成任务直接复用任务号
- rejected：AI 未启用/无激活配置/冷却中 → 不报错，返回 rejected 任务对象与降级消息
- 增量查询：读任务行 + 已就绪结果（毫秒级，不触发前端超时）
"""

import asyncio
import uuid
import weakref

from sqlalchemy.orm import Session

from app.ai.ai_settings import AiSettings
from app.ai.config.service import ModelConfigService
from app.ai.models import AiBatchTaskRow, AiMatchResultRow
from app.ai.repositories import (
    AiBatchTaskRepository,
    AiGreetingRepository,
    AiMatchCacheRepository,
)
from app.config import DEFAULT_USER_ID, settings
from app.infra.logging import get_logger

logger = get_logger("ai_tasks")

_running_tasks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


def _new_task_id() -> str:
    return str(uuid.uuid4())


def _get_resume_text(session: Session) -> tuple[str, str]:
    """返回 (resume_text, user_id)：默认简历解密全文（AI 匹配缓存指纹源）。"""
    from app.repositories.repos import ResumeRepository
    from app.services.resume_service import ResumeService
    from app.config import settings as app_settings
    from app.infra.crypto import get_crypto

    repo = ResumeRepository(session)
    resume = repo.get_default(DEFAULT_USER_ID)
    if resume is None:
        return "", DEFAULT_USER_ID
    service = ResumeService(session, get_crypto(), app_settings.resume_storage_dir)
    _profile, content = service.get_decrypted(DEFAULT_USER_ID, resume.resume_id)
    return content, DEFAULT_USER_ID


def _recommendation_positions(session: Session, top_n: int) -> list:
    """推荐展示范围职位集合（与 GET /recommendations 同 top_n 口径，D1：只读不改）。"""
    from app.services.matching_service import MatchingService
    from app.services.resume_service import ResumeService
    from app.config import settings as app_settings
    from app.infra.crypto import get_crypto

    resume_service = ResumeService(session, get_crypto(), app_settings.resume_storage_dir)
    scored = MatchingService(session, resume_service).scored_positions(DEFAULT_USER_ID)
    items = scored[:top_n] if top_n > 0 else scored
    return [item["position"] for item in items]


class AiTaskOrchestrator:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------- 匹配批任务发起 ----------

    async def create_matching_task(self, top_n: int = 50) -> dict:
        """幂等发起：rejected 场景不报错返回降级消息；否则返回 202 任务号。"""
        repo = AiBatchTaskRepository(self._session)
        ai_settings = AiSettings(self._session)

        availability = ModelConfigService(self._session).availability()
        if availability["state"] != "ready":
            reason = "ai_disabled" if not ai_settings.enabled else availability["state"]
            row = repo.create(
                kind="match", user_id=DEFAULT_USER_ID, top_n=top_n,
                total=0,
            )
            repo.set_status(row.task_id, "rejected", availability["message"])
            self._session.commit()
            return {"task_id": row.task_id, "status": "rejected", "degrade_message": availability["message"], "done": 0, "total": 0}

        existing = repo.find_recent_running("match", DEFAULT_USER_ID, top_n)
        if existing is not None:
            return self._task_view(existing)

        positions = _recommendation_positions(self._session, top_n)
        row = repo.create(kind="match", user_id=DEFAULT_USER_ID, top_n=top_n, total=len(positions))
        repo.set_status(row.task_id, "running")
        self._session.commit()
        task_id = row.task_id

        background = asyncio.create_task(self._run_matching(task_id, top_n))
        _running_tasks[task_id] = background
        return self._task_view(repo.get(task_id))

    async def _run_matching(self, task_id: str, top_n: int) -> None:
        """后台执行：逐职位评分（Semaphore 3）→ 进度更新 → 完成 LRU 清理。"""
        from app.ai.matching.service import AiMatchingService
        from app.ai.repositories import AiBatchTaskRepository

        session = _new_session()
        try:
            repo = AiBatchTaskRepository(session)
            row = repo.get(task_id)
            if row is None:
                return
            resume_text, user_id = _get_resume_text(session)
            if not resume_text.strip():
                repo.set_status(task_id, "rejected", "未找到默认简历，AI 匹配未执行")
                session.commit()
                return
            positions = _recommendation_positions(session, top_n)

            service = AiMatchingService(session)
            done = 0
            fallback = 0

            def on_progress(position_id: str, result: dict) -> None:
                nonlocal done, fallback
                done += 1
                if result.get("status") != "ok":
                    fallback += 1
                try:
                    repo.update_progress(task_id, done, fallback)
                    session.commit()
                except Exception:  # noqa: BLE001
                    session.rollback()

            await service.score_batch(user_id, resume_text, positions, on_progress)
            repo.update_progress(task_id, done, fallback, status="completed")
            session.commit()
            cache_repo = AiMatchCacheRepository(session)
            cache_repo.lru_cleanup()
            repo.lru_cleanup()
            session.commit()
            logger.info("ai_matching_task_completed", task_id=task_id, done=done, fallback=fallback)
        except Exception:  # noqa: BLE001
            logger.exception("ai_matching_task_failed", task_id=task_id)
            _safe_set_status(task_id, "rejected", "任务执行异常，已回退规则评分")
        finally:
            session.close()

    # ---------- 匹配任务查询（增量） ----------

    def matching_task_result(self, task_id: str) -> dict:
        """增量查询：任务行 + 已就绪职位评分（毫秒级）。任务不存在沿用 40401。"""
        from app.api.v1.errors import NotFoundError

        repo = AiBatchTaskRepository(self._session)
        row = repo.get(task_id)
        if row is None:
            raise NotFoundError(f"AI 任务不存在: {task_id}")
        view = self._task_view(row)

        if row.kind != "match":
            return view

        items: list[dict] = []
        if row.status in ("running", "completed"):
            resume_text, user_id = _get_resume_text(self._session)
            if resume_text:
                from app.ai.matching.service import resume_hash_of

                r_hash = resume_hash_of(resume_text)
                positions = _recommendation_positions(self._session, row.top_n)
                cache = AiMatchCacheRepository(self._session)
                from app.ai.models import AiMatchResultRow  # noqa: F401

                for position in positions:
                    cached = _find_any_score(self._session, user_id, r_hash, position.position_id)
                    if cached is not None:
                        items.append(
                            {
                                "position_id": position.position_id,
                                "ai_score": cached.score,
                                "reason": cached.reason,
                                "status": "ok",
                            }
                        )
                # fallback 计数与 done 差额 = 待完成/失败职位（前端保持规则分）
        view["items"] = items
        view["ai_state_summary"] = _state_summary(row)
        return view

    # ---------- 招呼语批任务 ----------

    async def prepare_greetings(self, delivery_task_id: str) -> dict:
        """prepare：缓存命中立即就绪；未命中入后台生成；AI 不可用全部 template。"""
        from app.repositories.repos import TaskRepository

        task_repo = TaskRepository(self._session)
        task = task_repo.get(delivery_task_id)
        if task is None:
            from app.api.v1.errors import NotFoundError

            raise NotFoundError(f"投递任务不存在: {delivery_task_id}")

        repo = AiBatchTaskRepository(self._session)
        existing = repo.find_recent_running("greeting", DEFAULT_USER_ID, len(task.target_position_ids))
        greet_positions = [
            p for p in _positions_by_ids(self._session, task.target_position_ids)
            if p.platform_id in {"boss_zhipin", "mock_platform"}
        ]
        row = repo.create(
            kind="greeting", user_id=DEFAULT_USER_ID,
            top_n=len(task.target_position_ids),
            delivery_task_id=delivery_task_id,
            total=len(greet_positions),
        )
        repo.set_status(row.task_id, "running")
        self._session.commit()
        task_id = row.task_id

        background = asyncio.create_task(self._run_greetings(task_id, delivery_task_id))
        _running_tasks[task_id] = background
        return self._task_view(repo.get(task_id))

    async def _run_greetings(self, task_id: str, delivery_task_id: str) -> None:
        from app.ai.greeting.service import GreetingService
        from app.ai.repositories import AiBatchTaskRepository

        session = _new_session()
        try:
            repo = AiBatchTaskRepository(session)
            row = repo.get(task_id)
            if row is None:
                return
            task_row = _get_delivery_task(session, delivery_task_id)
            if task_row is None:
                repo.set_status(task_id, "rejected", "投递任务不存在")
                session.commit()
                return
            positions = [
                p for p in _positions_by_ids(session, task_row.target_position_ids)
                if p.platform_id in {"boss_zhipin", "mock_platform"}
            ]
            resume_text, user_id = _get_resume_text(session)

            service = GreetingService(session)
            progress = {"done": 0, "fallback": 0}
            semaphore = asyncio.Semaphore(settings.ai_concurrency)

            async def _one(position) -> None:
                async with semaphore:
                    result = await service.generate_one(user_id, resume_text or "", position, delivery_task_id)
                    progress["done"] += 1
                    if result.get("status") != "ok":
                        progress["fallback"] += 1
                    repo.update_progress(task_id, progress["done"], progress["fallback"])
                    session.commit()

            await asyncio.gather(*[_one(p) for p in positions], return_exceptions=True)
            repo.update_progress(task_id, progress["done"], progress["fallback"], status="completed")
            session.commit()
            repo.lru_cleanup()
            session.commit()
            logger.info("greeting_task_completed", task_id=task_id, done=progress["done"])
        except Exception:  # noqa: BLE001
            logger.exception("greeting_task_failed", task_id=task_id)
            _safe_set_status(task_id, "rejected", "招呼语生成异常，已回退固定模板")
        finally:
            session.close()

    # ---------- 视图 ----------

    @staticmethod
    def _task_view(row: AiBatchTaskRow) -> dict:
        return {
            "task_id": row.task_id,
            "kind": row.kind,
            "status": row.status,
            "total": row.total,
            "done": row.done,
            "fallback_count": row.fallback_count,
            "degrade_message": row.degrade_message or "",
            "delivery_task_id": row.delivery_task_id or "",
        }


def _state_summary(row: AiBatchTaskRow) -> str:
    if row.status == "rejected":
        return "off"
    if row.done == 0:
        return "off"
    if row.fallback_count == 0:
        return "all_ai"
    if row.fallback_count >= row.done:
        return "all_fallback"
    return "partial"


def _find_any_score(session: Session, user_id: str, r_hash: str, position_id: str):
    """按 (user, resume, position) 查任一 jd_hash 的最新缓存评分（增量查询用）。"""
    from sqlalchemy import select

    from app.ai.models import AiMatchResultRow

    return session.scalar(
        select(AiMatchResultRow)
        .where(
            AiMatchResultRow.user_id == user_id,
            AiMatchResultRow.resume_hash == r_hash,
            AiMatchResultRow.position_id == position_id,
        )
        .order_by(AiMatchResultRow.generated_at.desc())
    )


def _positions_by_ids(session: Session, position_ids: list) -> list:
    from app.repositories.repos import PositionRepository

    return PositionRepository(session).get_by_ids(position_ids)


def _get_delivery_task(session: Session, delivery_task_id: str):
    from app.repositories.repos import TaskRepository

    return TaskRepository(session).get(delivery_task_id)


def _new_session():
    from app.infra.database import get_database

    return get_database().session()


def _safe_set_status(task_id: str, status: str, message: str) -> None:
    session = _new_session()
    try:
        AiBatchTaskRepository(session).set_status(task_id, status, message)
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()