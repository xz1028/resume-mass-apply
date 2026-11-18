"""投递黑名单 REST API（design 2.2.2 接口组 3）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_blacklist_service, get_current_user_id
from app.services.blacklist_service import BlacklistService

router = APIRouter(prefix="/api/v1/blacklist", tags=["blacklist"])


class BlacklistEntryDTO(BaseModel):
    entry_id: str
    type: str
    content: str


class AddBlacklistRequest(BaseModel):
    type: str
    content: str


@router.post("", response_model=BlacklistEntryDTO)
def add_blacklist_entry(
    req: AddBlacklistRequest,
    user_id: str = Depends(get_current_user_id),
    svc: BlacklistService = Depends(get_blacklist_service),
) -> BlacklistEntryDTO:
    entry = svc.add(user_id, req.type, req.content)
    return BlacklistEntryDTO(entry_id=entry.entry_id, type=entry.type.value, content=entry.content)


@router.get("", response_model=list[BlacklistEntryDTO])
def list_blacklist(
    user_id: str = Depends(get_current_user_id),
    svc: BlacklistService = Depends(get_blacklist_service),
) -> list[BlacklistEntryDTO]:
    return [
        BlacklistEntryDTO(entry_id=e.entry_id, type=e.type.value, content=e.content)
        for e in svc.list(user_id)
    ]


@router.delete("/{entry_id}", status_code=204)
def delete_blacklist_entry(
    entry_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: BlacklistService = Depends(get_blacklist_service),
) -> None:
    svc.delete(user_id, entry_id)