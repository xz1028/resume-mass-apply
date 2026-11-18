"""职位推荐与匹配阈值 REST API（design 2.2.2 接口 4.2 / 4.3）。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user_id, get_matching_service
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/api/v1", tags=["matching"])


class RecommendedPositionDTO(BaseModel):
    position_id: str
    platform_id: str
    title: str
    company: str
    city: str
    salary_min: int | None
    salary_max: int | None
    industry: str
    experience_req: str
    publish_expire_at: datetime
    fetched_at: datetime
    match_score: int | None


class RecommendationResponse(BaseModel):
    matching_unavailable: bool
    message: str | None
    items: list[RecommendedPositionDTO]


class MatchingSettingsDTO(BaseModel):
    auto_apply_threshold: int


def _to_dto(item: dict) -> RecommendedPositionDTO:
    p = item["position"]
    return RecommendedPositionDTO(
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
        fetched_at=p.fetched_at,
        match_score=item["match_score"],
    )


@router.get("/recommendations", response_model=RecommendationResponse)
def get_recommendations(
    top_n: int = 50,
    user_id: str = Depends(get_current_user_id),
    svc: MatchingService = Depends(get_matching_service),
) -> RecommendationResponse:
    top_n = max(1, min(top_n, 500))
    result = svc.get_recommendations(user_id, top_n)
    return RecommendationResponse(
        matching_unavailable=result["matching_unavailable"],
        message=result["message"],
        items=[_to_dto(i) for i in result["items"]],
    )


@router.put("/matching-settings", response_model=MatchingSettingsDTO)
def set_matching_settings(
    req: MatchingSettingsDTO,
    svc: MatchingService = Depends(get_matching_service),
) -> MatchingSettingsDTO:
    threshold = svc.set_threshold(req.auto_apply_threshold)
    return MatchingSettingsDTO(auto_apply_threshold=threshold)