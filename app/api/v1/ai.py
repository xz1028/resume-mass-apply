"""AI 组件 REST API（14 个接口 + 错误码 43001-43006）。

命名空间：/api/v1/ai/*（独立前缀，既有接口零改动）。
安全红线：DTO 永不返回 api_key 字段（仅 has_api_key: bool）；
测试草稿 Key 不落库；put 时审计关键变更。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.v1.errors import InvalidParamError, NotFoundError
from app.ai.ai_settings import AiSettings
from app.ai.config.service import ModelConfigService
from app.ai.greeting.service import GreetingService
from app.ai.tasks import AiTaskOrchestrator

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ---------- DTO ----------


class ModelConfigCreateReq(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider: str
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None


class ModelConfigUpdateReq(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None


class ActivateReq(BaseModel):
    force: bool = False


class TestDraftReq(BaseModel):
    draft_key: str | None = None


class AiSettingsDTO(BaseModel):
    ai_enabled: bool = True
    ai_mask_enabled: bool = True
    ai_mask_fields: list[str] = Field(default_factory=lambda: ["phone", "email"])
    ai_jd_truncate_limit: int = Field(gt=0, le=20000)
    ai_resume_truncate_limit: int = Field(gt=0, le=50000)
    ai_greeting_max_len: int = Field(gt=0, le=1000)
    ai_greeting_tone: str = "professional"
    ai_send_full_resume: bool = False


class GreetingEditReq(BaseModel):
    text: str = Field(min_length=1)


# ---------- 模型配置管理（6 接口） ----------


@router.get("/model-configs")
def list_model_configs(session: Session = Depends(get_session)) -> list[dict]:
    return ModelConfigService(session).list_configs()


@router.post("/model-configs", status_code=201)
def create_model_config(
    req: ModelConfigCreateReq,
    session: Session = Depends(get_session),
) -> dict:
    return ModelConfigService(session).create_config(
        name=req.name,
        provider=req.provider,
        base_url=req.base_url,
        model_name=req.model_name,
        api_key=req.api_key,
    )


@router.put("/model-configs/{config_id}")
def update_model_config(
    config_id: str,
    req: ModelConfigUpdateReq,
    session: Session = Depends(get_session),
) -> dict:
    return ModelConfigService(session).update_config(
        config_id=config_id,
        name=req.name,
        base_url=req.base_url,
        model_name=req.model_name,
        api_key=req.api_key,
    )


@router.delete("/model-configs/{config_id}", status_code=204)
def delete_model_config(
    config_id: str,
    session: Session = Depends(get_session),
) -> None:
    ModelConfigService(session).delete_config(config_id)


@router.post("/model-configs/{config_id}/test")
async def test_model_config(
    config_id: str,
    req: TestDraftReq | None = None,
    session: Session = Depends(get_session),
) -> dict:
    draft_key = req.draft_key if req else None
    return await ModelConfigService(session).test_config(config_id, draft_key)


@router.post("/model-configs/{config_id}/activate")
def activate_model_config(
    config_id: str,
    req: ActivateReq | None = None,
    session: Session = Depends(get_session),
) -> dict:
    force = req.force if req else False
    return ModelConfigService(session).activate_config(config_id, force)


# ---------- 设置与状态（3 接口） ----------


@router.get("/settings", response_model=AiSettingsDTO)
def get_ai_settings(session: Session = Depends(get_session)) -> dict:
    return AiSettings(session).get_all()


@router.put("/settings", response_model=AiSettingsDTO)
def update_ai_settings(
    req: AiSettingsDTO,
    session: Session = Depends(get_session),
) -> dict:
    """更新用户级设置：脱敏与启停变更记审计；send_full_resume 回传风险提示。"""
    from app.infra.audit import AuditAction, record_audit

    current = AiSettings(session).get_all()
    settings = AiSettings(session)
    privacy_changed = (
        req.ai_mask_enabled != current["ai_mask_enabled"]
        or req.ai_mask_fields != current["ai_mask_fields"]
        or req.ai_send_full_resume != current["ai_send_full_resume"]
    )
    toggled = req.ai_enabled != current["ai_enabled"]
    for field_name, value in req.model_dump().items():
        settings.set(field_name, value)
    if privacy_changed:
        record_audit(
            session,
            AuditAction.AI_PRIVACY_SETTINGS_CHANGED,
            f"脱敏设置变更（mask={req.ai_mask_enabled}, fields={req.ai_mask_fields}, full_resume={req.ai_send_full_resume}）",
        )
    if toggled:
        record_audit(
            session,
            AuditAction.AI_FEATURE_TOGGLED,
            f"AI 功能{'启用' if req.ai_enabled else '停用'}",
        )
    session.commit()
    result = req.model_dump()
    if req.ai_send_full_resume:
        result["risk_notice"] = (
            "已选择发送完整简历：您的联系方式（手机号/邮箱）将明文发送至所配置的模型服务，请注意隐私风险"
        )
    return result


@router.get("/status")
def get_ai_status(session: Session = Depends(get_session)) -> dict:
    availability = ModelConfigService(session).availability()
    active_config = None
    provider = None
    if availability.get("active_config"):
        from app.ai.repositories import ModelConfigRepository

        active = ModelConfigRepository(session).get_active()
        if active is not None:
            active_config = active.name
            provider = active.provider
    return {
        "state": availability["state"],
        "message": availability["message"],
        "active_config_name": active_config,
        "provider": provider,
    }


# ---------- 匹配批任务（2 接口） ----------


@router.post("/matching-tasks", status_code=202)
async def create_matching_task(
    top_n: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    top_n = max(1, min(top_n, 500))
    return await AiTaskOrchestrator(session).create_matching_task(top_n)


@router.get("/matching-tasks/{task_id}")
def get_matching_task(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    return AiTaskOrchestrator(session).matching_task_result(task_id)


# ---------- 招呼语（3 接口） ----------


@router.post("/delivery-tasks/{task_id}/greetings/prepare", status_code=202)
async def prepare_greetings(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    return await AiTaskOrchestrator(session).prepare_greetings(task_id)


@router.get("/delivery-tasks/{task_id}/greetings")
def list_greetings(
    task_id: str,
    session: Session = Depends(get_session),
) -> dict:
    service = GreetingService(session)
    items = service.list_for_task(task_id)

    from sqlalchemy import select

    from app.ai.models import AiBatchTaskRow

    row = session.scalar(
        select(AiBatchTaskRow).where(
            AiBatchTaskRow.kind == "greeting",
            AiBatchTaskRow.delivery_task_id == task_id,
        ).order_by(AiBatchTaskRow.created_at.desc())
    )
    all_ready = row is not None and row.status in ("completed", "rejected")
    return {
        "all_ready": all_ready,
        "status": row.status if row else "none",
        "items": items,
    }


@router.put("/delivery-tasks/{task_id}/greetings/{position_id}")
def edit_greeting(
    task_id: str,
    position_id: str,
    req: GreetingEditReq,
    session: Session = Depends(get_session),
) -> dict:
    return GreetingService(session).edit(task_id, position_id, req.text)