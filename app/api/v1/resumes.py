"""简历管理 REST API（design 2.2.2 接口组 1）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from app.api.deps import get_current_user_id, get_resume_service
from app.services.resume_service import ResumeService

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])


class ResumeProfileDTO(BaseModel):
    resume_id: str
    name: str
    format: str
    size_bytes: int
    is_default: bool
    created_at: datetime


class RenameRequest(BaseModel):
    name: str


def _to_dto(resume) -> ResumeProfileDTO:
    return ResumeProfileDTO(
        resume_id=resume.resume_id,
        name=resume.name,
        format=resume.format.value,
        size_bytes=resume.size_bytes,
        is_default=resume.is_default,
        created_at=resume.created_at,
    )


@router.post("", response_model=ResumeProfileDTO)
async def upload_resume(
    file: UploadFile,
    user_id: str = Depends(get_current_user_id),
    svc: ResumeService = Depends(get_resume_service),
) -> ResumeProfileDTO:
    content = await file.read()
    return _to_dto(svc.upload(user_id, file.filename or "resume", content))


@router.get("", response_model=list[ResumeProfileDTO])
def list_resumes(
    user_id: str = Depends(get_current_user_id),
    svc: ResumeService = Depends(get_resume_service),
) -> list[ResumeProfileDTO]:
    return [_to_dto(r) for r in svc.list(user_id)]


@router.patch("/{resume_id}", response_model=ResumeProfileDTO)
def rename_resume(
    resume_id: str,
    req: RenameRequest,
    user_id: str = Depends(get_current_user_id),
    svc: ResumeService = Depends(get_resume_service),
) -> ResumeProfileDTO:
    return _to_dto(svc.rename(user_id, resume_id, req.name))


@router.put("/{resume_id}/default", response_model=ResumeProfileDTO)
def set_default_resume(
    resume_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResumeService = Depends(get_resume_service),
) -> ResumeProfileDTO:
    return _to_dto(svc.set_default(user_id, resume_id))


@router.delete("/{resume_id}", status_code=204)
def delete_resume(
    resume_id: str,
    user_id: str = Depends(get_current_user_id),
    svc: ResumeService = Depends(get_resume_service),
) -> None:
    svc.delete(user_id, resume_id)