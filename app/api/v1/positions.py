"""职位查询 REST API（design 2.2.2 接口 4.1）。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user_id, get_job_service
from app.services.job_service import JobService

router = APIRouter(prefix="/api/v1/positions", tags=["positions"])


class PositionDTO(BaseModel):
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


class PositionPageDTO(BaseModel):
    items: list[PositionDTO]
    total: int
    page: int
    page_size: int
    not_updated_platforms: list[str] = []
    suggestion: str | None = None


def _to_dto(p) -> PositionDTO:
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
        fetched_at=p.fetched_at,
    )


@router.get("", response_model=PositionPageDTO)
def list_positions(
    city: str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    industry: str | None = None,
    keyword: str | None = None,
    experience: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    svc: JobService = Depends(get_job_service),
) -> PositionPageDTO:
    items, total = svc.list_positions(
        user_id,
        city=city,
        salary_min=salary_min,
        salary_max=salary_max,
        industry=industry,
        keyword=keyword,
        experience=experience,
        page=page,
        page_size=page_size,
    )
    has_filter = any([city, salary_min, salary_max, industry, keyword, experience])
    return PositionPageDTO(
        items=[_to_dto(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        not_updated_platforms=svc.stale_platforms(),
        suggestion="当前条件下暂无职位，建议扩大薪资范围或更换城市"
        if total == 0 and has_filter
        else None,
    )