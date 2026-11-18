"""投递记录与统计 REST API（design 2.2.2 接口组 6）。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_session
from app.repositories.repos import PositionRepository, RecordRepository
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/api/v1", tags=["delivery-records"])


class ResumeSnapshotDTO(BaseModel):
    name: str
    format: str
    content_hash: str
    created_at: datetime


class DeliveryRecordDTO(BaseModel):
    record_id: str
    task_id: str
    position_id: str
    platform_id: str
    position_title: str
    company: str
    status: str
    delivered_at: datetime | None
    status_updated_at: datetime
    failure_reason: str | None
    resume_snapshot: ResumeSnapshotDTO


class RecordPageDTO(BaseModel):
    items: list[DeliveryRecordDTO]
    total: int
    page: int
    page_size: int


class StatisticsDTO(BaseModel):
    total: int
    status_distribution: dict[str, int]
    platform_distribution: dict[str, int]
    recent_7_days: list[dict]


@router.get("/delivery-records", response_model=RecordPageDTO)
def list_delivery_records(
    status: str | None = None,
    platform: str | None = None,
    since: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> RecordPageDTO:
    records, total = RecordRepository(session).list_by_user(
        user_id,
        status=status,
        platform_id=platform,
        since=since,
        page=page,
        page_size=page_size,
    )
    positions = {
        p.position_id: p
        for p in PositionRepository(session).get_by_ids([r.position_id for r in records])
    }
    items = []
    for r in records:
        position = positions.get(r.position_id)
        items.append(
            DeliveryRecordDTO(
                record_id=r.record_id,
                task_id=r.task_id,
                position_id=r.position_id,
                platform_id=r.platform_id,
                position_title=position.title if position else "",
                company=position.company if position else "",
                status=r.status.value,
                delivered_at=r.delivered_at,
                status_updated_at=r.status_updated_at,
                failure_reason=r.failure_reason,
                resume_snapshot=ResumeSnapshotDTO(
                    name=r.resume_snapshot.name,
                    format=r.resume_snapshot.format,
                    content_hash=r.resume_snapshot.content_hash,
                    created_at=r.resume_snapshot.created_at,
                ),
            )
        )
    return RecordPageDTO(items=items, total=total, page=page, page_size=page_size)


@router.get("/delivery-statistics", response_model=StatisticsDTO)
def get_delivery_statistics(
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    return RecordRepository(session).statistics(user_id)