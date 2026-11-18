"""匹配服务：推荐列表生成、结果缓存、不可解析降级、阈值管理。"""

import hashlib
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v1.errors import InvalidParamError, NotFoundError
from app.config import settings
from app.domain.models import JobIntention, JobPosition
from app.infra.logging import get_logger
from app.matching.engine import MatchScore, WeightedFactorEngine
from app.parsers.resume_parser import DefaultResumeParser
from app.repositories.repos import (
    BlacklistRepository,
    PositionRepository,
    ResumeRepository,
    SeekerRepository,
    SettingRepository,
)
from app.services.blacklist_service import BlacklistService
from app.services.resume_service import ResumeService

logger = get_logger("matching_service")

THRESHOLD_KEY = "auto_apply_threshold"

_cache: dict[tuple, tuple[float, list[dict]]] = {}


class MatchingService:
    def __init__(self, session: Session, resume_service: ResumeService) -> None:
        self._session = session
        self._resume_service = resume_service
        self._parser = DefaultResumeParser()

    def get_recommendations(self, user_id: str, top_n: int = 50) -> dict:
        """以默认简历对职位池逐职位计算匹配度，按匹配度降序返回。

        简历不可解析（扫描件）时跳过匹配计算，按拉取时间排序返回并附降级标记。
        """
        resume = ResumeRepository(self._session).get_default(user_id)
        if resume is None:
            raise NotFoundError("请先上传简历并设置默认简历档案")

        _, content = self._resume_service.get_decrypted(user_id, resume.resume_id)
        content_hash = hashlib.sha256(content).hexdigest()
        positions = self._candidate_positions(user_id)
        fingerprint = self._positions_fingerprint(positions)

        cache_key = (user_id, resume.resume_id, content_hash, fingerprint)
        cached = _cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= settings.matching_cache_ttl_seconds:
            logger.info("matching_cache_hit", user_id=user_id)
            return {"matching_unavailable": False, "message": None,
                    "items": cached[1][:top_n]}

        raw = self._parser.extract_text(resume.name, resume.format.value, content)
        if not raw.parseable:
            logger.info("matching_unavailable", user_id=user_id, resume_id=resume.resume_id)
            return {
                "matching_unavailable": True,
                "message": "当前简历无法解析文本，匹配功能暂不可用，建议上传文字版简历",
                "items": [
                    {"position": p, "match_score": None} for p in positions[:top_n]
                ],
            }

        profile = SeekerRepository(self._session).get_or_create(user_id)
        engine = WeightedFactorEngine(
            weights={
                "skill": settings.weight_skill,
                "experience": settings.weight_experience,
                "city": settings.weight_city,
                "salary": settings.weight_salary,
            },
            intention=profile.intention,
        )
        resume_profile = engine.build_resume_profile(raw)
        scored: list[tuple[JobPosition, MatchScore]] = [
            (p, engine.compute_score(resume_profile, self._to_position_dto(p)))
            for p in positions
        ]
        scored.sort(key=lambda item: item[1].value, reverse=True)
        items = [{"position": p, "match_score": s.value} for p, s in scored]
        _cache[cache_key] = (now, items)
        if len(_cache) > 16:
            _cache.pop(next(iter(_cache)))
        return {"matching_unavailable": False, "message": None, "items": items[:top_n]}

    def scored_positions(self, user_id: str) -> list[dict]:
        """全量职位匹配评分（供条件圈选），复用推荐缓存。"""
        result = self.get_recommendations(user_id, top_n=10**6)
        return result["items"]

    def set_threshold(self, threshold: int) -> int:
        if not 0 <= threshold <= 100:
            raise InvalidParamError("匹配阈值必须在 0-100 之间")
        SettingRepository(self._session).set(THRESHOLD_KEY, threshold)
        self._session.commit()
        logger.info("matching_threshold_set", threshold=threshold)
        return threshold

    def get_threshold(self) -> int:
        return int(
            SettingRepository(self._session).get(THRESHOLD_KEY, settings.auto_apply_threshold)
        )

    def _candidate_positions(self, user_id: str) -> list[JobPosition]:
        entries = BlacklistRepository(self._session).list_by_user(user_id)
        companies, keywords = BlacklistService.split(entries)
        positions, _total = PositionRepository(self._session).list_active(
            page=1, page_size=100000,
            blacklist_companies=companies, blacklist_keywords=keywords,
        )
        return positions

    @staticmethod
    def _positions_fingerprint(positions: list[JobPosition]) -> tuple:
        if not positions:
            return (0, "")
        max_fetched = max(p.fetched_at for p in positions)
        return (len(positions), max_fetched.isoformat())

    @staticmethod
    def _to_position_dto(p: JobPosition):
        from app.platforms.spi import PositionDTO

        return PositionDTO(
            position_id=p.position_id,
            platform_id=p.platform_id,
            title=p.title,
            company=p.company,
            city=p.city,
            salary_min=p.salary_min,
            salary_max=p.salary_max,
            industry=p.industry,
            experience_req=p.experience_req,
            publish_expire_at=p.publish_expire_at,
        )