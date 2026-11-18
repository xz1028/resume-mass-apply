"""平台授权 REST API（design 2.2.2 接口组 7）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_authorization_service, get_current_user_id, get_session
from app.services.authorization_service import AuthorizationService

router = APIRouter(prefix="/api/v1/platforms", tags=["platforms"])


class PlatformDTO(BaseModel):
    platform_id: str
    name: str
    auth_status: str
    degraded: bool


class AuthorizationRequest(BaseModel):
    credential: str


@router.get("", response_model=list[PlatformDTO])
def list_platforms(
    svc: AuthorizationService = Depends(get_authorization_service),
) -> list[dict]:
    return svc.list_platforms()


@router.post("/{platform_id}/authorization", response_model=PlatformDTO)
def authorize(
    platform_id: str,
    req: AuthorizationRequest,
    user_id: str = Depends(get_current_user_id),
    svc: AuthorizationService = Depends(get_authorization_service),
) -> dict:
    return svc.authorize(user_id, platform_id, req.credential)


@router.delete("/{platform_id}/authorization", status_code=204)
def revoke(
    platform_id: str,
    user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
    svc: AuthorizationService = Depends(get_authorization_service),
) -> None:
    svc.revoke(user_id, platform_id)