"""职位获取与筛选服务：拉取结构化、失败降级、去重、过期清理、多条件筛选。"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import DEFAULT_USER_ID
from app.domain.models import AuthStatus, JobIntention, JobPosition
from app.infra.logging import get_logger
from app.platforms.registry import AdapterRegistry
from app.platforms.spi import PlatformError
from app.repositories.repos import (
    AuthorizationRepository,
    BlacklistRepository,
    PositionRepository,
    SeekerRepository,
)
from app.services.blacklist_service import BlacklistService

logger = get_logger("job_service")

_stale_platforms: dict[str, datetime] = {}


class JobService:
    def __init__(self, session: Session, registry: AdapterRegistry) -> None:
        self._session = session
        self._registry = registry

    def fetch_positions(self, user_id: str = DEFAULT_USER_ID) -> dict:
        """按求职意向从已授权平台拉取职位并结构化入库。

        拉取失败降级：沿用上次成功数据，标记平台"数据暂时未更新"。
        """
        profile = SeekerRepository(self._session).get_or_create(user_id)
        intent = profile.intention
        auth_repo = AuthorizationRepository(self._session)
        pos_repo = PositionRepository(self._session)
        now = datetime.now()
        results: dict[str, dict] = {}
        for platform_id, _name in self._registry.list_all():
            auth = auth_repo.get(platform_id)
            if auth is None or auth.status != AuthStatus.authorized:
                continue
            if self._registry.is_degraded(platform_id):
                results[platform_id] = {"status": "skipped", "reason": "平台降级中"}
                continue
            adapter = self._registry.get(platform_id)
            assert adapter is not None
            try:
                dtos = adapter.fetch_positions(intent, since=now - timedelta(days=1))
            except PlatformError as exc:
                self._registry.record_call_failure(platform_id)
                _stale_platforms[platform_id] = now
                logger.warning("position_fetch_failed", platform_id=platform_id, error=str(exc))
                results[platform_id] = {"status": "failed", "reason": str(exc)}
                continue
            self._registry.record_call_success(platform_id)
            _stale_platforms.pop(platform_id, None)
            for dto in dtos:
                pos_repo.upsert(
                    JobPosition(
                        position_id=dto.position_id,
                        platform_id=dto.platform_id,
                        title=dto.title,
                        company=dto.company,
                        city=dto.city,
                        salary_min=dto.salary_min,
                        salary_max=dto.salary_max,
                        industry=dto.industry,
                        experience_req=dto.experience_req,
                        publish_expire_at=dto.publish_expire_at,
                        fetched_at=now,
                        expired=False,
                    )
                )
            results[platform_id] = {"status": "ok", "fetched": len(dtos)}
            logger.info("positions_fetched", platform_id=platform_id, count=len(dtos))
        self._session.commit()
        return results

    def cleanup_expired(self) -> int:
        """过期清理：发布有效期已过的职位软删除（expired 标记）。"""
        count = PositionRepository(self._session).mark_expired(datetime.now())
        self._session.commit()
        if count:
            logger.info("positions_expired", count=count)
        return count

    def list_positions(
        self,
        user_id: str,
        city: str | None = None,
        salary_min: int | None = None,
        salary_max: int | None = None,
        industry: str | None = None,
        keyword: str | None = None,
        experience: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[JobPosition], int]:
        """多条件筛选：自动应用去重（唯一键）、黑名单过滤与过期过滤。"""
        entries = BlacklistRepository(self._session).list_by_user(user_id)
        companies, keywords = BlacklistService.split(entries)
        return PositionRepository(self._session).list_active(
            city=city,
            salary_min=salary_min,
            salary_max=salary_max,
            industry=industry,
            keyword=keyword,
            experience=experience,
            page=page,
            page_size=page_size,
            blacklist_companies=companies,
            blacklist_keywords=keywords,
        )

    def active_positions_for_matching(self, user_id: str) -> list[JobPosition]:
        """推荐候选集：全部未过期职位（黑名单过滤后）。"""
        entries = BlacklistRepository(self._session).list_by_user(user_id)
        companies, keywords = BlacklistService.split(entries)
        positions, _total = PositionRepository(self._session).list_active(
            page=1,
            page_size=100000,
            blacklist_companies=companies,
            blacklist_keywords=keywords,
        )
        return positions

    @staticmethod
    def stale_platforms() -> list[str]:
        return list(_stale_platforms.keys())


def make_recovery_fetcher(registry: AdapterRegistry):
    """平台恢复探测成功后自动补拉职位数据（注册到 registry.on_recovery）。"""

    def callback(platform_id: str) -> None:
        from app.infra.database import get_database

        session = get_database().session()
        try:
            JobService(session, registry).fetch_positions(DEFAULT_USER_ID)
            logger.info("recovery_refetch_done", platform_id=platform_id)
        except Exception:  # noqa: BLE001
            logger.exception("recovery_refetch_failed", platform_id=platform_id)
        finally:
            session.close()

    return callback