"""求职档案与意向 REST API（design 2.2.2 接口组 2）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user_id, get_profile_service
from app.domain.models import ContactInfo, JobIntention
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


class ContactInfoDTO(BaseModel):
    phone: str | None = None
    email: str | None = None


class JobIntentionDTO(BaseModel):
    city: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    industry: str | None = None


class SeekerProfileDTO(BaseModel):
    user_id: str
    contact: ContactInfoDTO
    intention: JobIntentionDTO


def _to_dto(profile) -> SeekerProfileDTO:
    return SeekerProfileDTO(
        user_id=profile.user_id,
        contact=ContactInfoDTO(phone=profile.contact.phone, email=profile.contact.email),
        intention=JobIntentionDTO(
            city=profile.intention.city,
            salary_min=profile.intention.salary_min,
            salary_max=profile.intention.salary_max,
            industry=profile.intention.industry,
        ),
    )


@router.get("", response_model=SeekerProfileDTO)
def get_profile(
    user_id: str = Depends(get_current_user_id),
    svc: ProfileService = Depends(get_profile_service),
) -> SeekerProfileDTO:
    return _to_dto(svc.get(user_id))


@router.put("", response_model=SeekerProfileDTO)
def update_profile(
    req: SeekerProfileDTO,
    user_id: str = Depends(get_current_user_id),
    svc: ProfileService = Depends(get_profile_service),
) -> SeekerProfileDTO:
    contact = ContactInfo(phone=req.contact.phone, email=req.contact.email)
    intention = JobIntention(
        city=req.intention.city,
        salary_min=req.intention.salary_min,
        salary_max=req.intention.salary_max,
        industry=req.intention.industry,
    )
    return _to_dto(svc.update(user_id, contact=contact, intention=intention))