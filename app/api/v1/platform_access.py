"""平台接入治理 REST API（10 个端点 + 错误码 42001-42004）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.platforms.registry import get_registry
from app.real_platform.access.auth_session import BrowserAuthSessionService
from app.real_platform.access.pending_events import (
    list_pending_events,
    open_handle_session,
)
from app.real_platform.access.service import PlatformAccessService

router = APIRouter(prefix="/api/v1/platform-access", tags=["platform-access"])


class AccessConfigDTO(BaseModel):
    platform_id: str
    name: str
    access_mode: str
    priority: str
    enabled: bool
    risk_confirmed: bool
    auth_status: str
    degraded: bool
    delivery_rate_per_hour: float
    fetch_interval_hours: int
    access_mode_note: str


class EnableResponse(BaseModel):
    platform_id: str
    enabled: bool


class RatePolicyRequest(BaseModel):
    delivery_rate_per_hour: float


class RatePolicyResponse(BaseModel):
    platform_id: str
    delivery_rate_per_hour: float


class AuthSessionResponse(BaseModel):
    session_id: str
    platform_id: str
    status: str
    remaining_seconds: int
    failure_reason: str | None = None


class ChallengeDTO(BaseModel):
    challenge_id: str
    platform_id: str
    stage: str
    remaining_seconds: int
    message: str


class RiskEventDTO(BaseModel):
    event_id: str
    platform_id: str
    event_type: str
    advice: str
    occurred_at: str


class PendingEventsResponse(BaseModel):
    challenges: list[ChallengeDTO]
    risk_events: list[RiskEventDTO]


class HandleChallengeResponse(BaseModel):
    challenge_id: str
    platform_id: str
    status: str
    message: str


def _access_service(session: Session = Depends(get_session)) -> PlatformAccessService:
    return PlatformAccessService(session, get_registry())


@router.get("", response_model=list[AccessConfigDTO])
def list_access_configs(
    svc: PlatformAccessService = Depends(_access_service),
) -> list[dict]:
    return svc.list_configs()


@router.post("/{platform_id}/risk-confirmation", status_code=204)
def confirm_risk(
    platform_id: str,
    svc: PlatformAccessService = Depends(_access_service),
) -> None:
    svc.confirm_risk(platform_id)


@router.post("/{platform_id}/enable", response_model=EnableResponse)
def enable_platform(
    platform_id: str,
    svc: PlatformAccessService = Depends(_access_service),
) -> dict:
    return svc.enable(platform_id)


@router.post("/{platform_id}/disable", response_model=EnableResponse)
def disable_platform(
    platform_id: str,
    svc: PlatformAccessService = Depends(_access_service),
) -> dict:
    return svc.disable(platform_id)


@router.put("/{platform_id}/rate-policy", response_model=RatePolicyResponse)
def update_rate_policy(
    platform_id: str,
    req: RatePolicyRequest,
    svc: PlatformAccessService = Depends(_access_service),
) -> dict:
    return svc.update_rate_policy(platform_id, req.delivery_rate_per_hour)


@router.post("/{platform_id}/browser-authorization", response_model=AuthSessionResponse)
def create_browser_authorization(
    platform_id: str,
    session: Session = Depends(get_session),
) -> dict:
    service = BrowserAuthSessionService(session, get_registry())
    return service.create_and_run(platform_id)


@router.get("/{platform_id}/browser-authorization/{session_id}", response_model=AuthSessionResponse)
def poll_browser_authorization(
    platform_id: str,
    session_id: str,
    session: Session = Depends(get_session),
) -> dict:
    service = BrowserAuthSessionService(session, get_registry())
    return service.poll(session_id)


@router.post("/{platform_id}/browser-authorization/{session_id}/cancel", status_code=204)
def cancel_browser_authorization(
    platform_id: str,
    session_id: str,
    session: Session = Depends(get_session),
) -> None:
    service = BrowserAuthSessionService(session, get_registry())
    service.cancel(session_id)


@router.get("/pending-events", response_model=PendingEventsResponse)
def get_pending_events(
    session: Session = Depends(get_session),
) -> dict:
    return list_pending_events(session, get_registry())


@router.post(
    "/{platform_id}/captcha-challenges/{challenge_id}/handle",
    response_model=HandleChallengeResponse,
)
def handle_captcha_challenge(
    platform_id: str,
    challenge_id: str,
    session: Session = Depends(get_session),
) -> dict:
    return open_handle_session(session, get_registry(), platform_id, challenge_id)