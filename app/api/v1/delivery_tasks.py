"""投递任务 REST API（design 2.2.2 接口组 5）。"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_delivery_service, get_session
from app.api.v1.errors import InvalidParamError
from app.repositories.repos import SettingRepository
from app.services.delivery_service import (
    DAILY_LIMIT_KEY,
    DeliveryService,
    run_delivery_task,
)

router = APIRouter(prefix="/api/v1", tags=["delivery-tasks"])


class FilterConditionDTO(BaseModel):
    city: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    industry: str | None = None
    keyword: str | None = None
    experience: str | None = None
    min_match_score: int | None = None


class CreateTaskRequest(BaseModel):
    position_ids: list[str] | None = None
    filter_condition: FilterConditionDTO | None = None


class RejectedItemDTO(BaseModel):
    position_id: str
    title: str
    reason: str


class ChecklistDTO(BaseModel):
    position_count: int
    platform_distribution: dict[str, int]
    resume_name: str
    rejected: list[RejectedItemDTO]


class DeliveryTaskDTO(BaseModel):
    task_id: str
    status: str
    created_at: datetime
    resume_name: str
    position_count: int
    success_count: int
    failed_count: int
    skipped_count: int


class CreateTaskResponse(BaseModel):
    task: DeliveryTaskDTO
    checklist: ChecklistDTO


class CancelResponse(BaseModel):
    task_id: str
    status: str
    delivered: int
    remaining: int


class DeliverySettingsDTO(BaseModel):
    daily_limit: int


def _task_to_dto(task, summary: dict | None = None) -> DeliveryTaskDTO:
    return DeliveryTaskDTO(
        task_id=task.task_id,
        status=task.status.value,
        created_at=task.created_at,
        resume_name=task.resume_snapshot.name,
        position_count=len(task.target_position_ids),
        success_count=task.success_count,
        failed_count=task.failed_count,
        skipped_count=task.skipped_count,
    )


@router.post("/delivery-tasks", response_model=CreateTaskResponse)
def create_delivery_task(
    req: CreateTaskRequest,
    user_id: str = Depends(get_current_user_id),
    svc: DeliveryService = Depends(get_delivery_service),
) -> CreateTaskResponse:
    filter_condition = req.filter_condition.model_dump() if req.filter_condition else None
    result = svc.create_task(user_id, position_ids=req.position_ids, filter_condition=filter_condition)
    task = result["task"]
    checklist = result["checklist"]
    return CreateTaskResponse(
        task=_task_to_dto(task),
        checklist=ChecklistDTO(
            position_count=checklist["position_count"],
            platform_distribution=checklist["platform_distribution"],
            resume_name=checklist["resume_name"],
            rejected=[RejectedItemDTO(**r) for r in checklist["rejected"]],
        ),
    )


@router.post("/delivery-tasks/{task_id}/confirm", response_model=DeliveryTaskDTO)
async def confirm_delivery_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: DeliveryService = Depends(get_delivery_service),
) -> DeliveryTaskDTO:
    task = svc.confirm_task(user_id, task_id)
    asyncio.create_task(run_delivery_task(task_id))
    return _task_to_dto(task)


@router.post("/delivery-tasks/{task_id}/cancel", response_model=CancelResponse)
def cancel_delivery_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: DeliveryService = Depends(get_delivery_service),
) -> dict:
    return svc.cancel_task(user_id, task_id)


@router.get("/delivery-tasks/{task_id}", response_model=DeliveryTaskDTO)
def get_delivery_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: DeliveryService = Depends(get_delivery_service),
) -> DeliveryTaskDTO:
    result = svc.get_task(user_id, task_id)
    return _task_to_dto(result["task"])


@router.put("/delivery-settings", response_model=DeliverySettingsDTO)
def set_delivery_settings(
    req: DeliverySettingsDTO,
    session: Session = Depends(get_session),
) -> DeliverySettingsDTO:
    if req.daily_limit < 1:
        raise InvalidParamError("每日投递上限必须 >= 1")
    SettingRepository(session).set(DAILY_LIMIT_KEY, req.daily_limit)
    session.commit()
    return DeliverySettingsDTO(daily_limit=req.daily_limit)