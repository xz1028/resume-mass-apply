"""求职者档案与意向管理：联系方式校验、意向更新与拉取条件联动。"""

from sqlalchemy.orm import Session

from app.api.v1.errors import InvalidParamError
from app.domain.models import ContactInfo, JobIntention, JobSeekerProfile
from app.infra.logging import get_logger
from app.repositories.repos import SeekerRepository

logger = get_logger("profile_service")


class ProfileService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str) -> JobSeekerProfile:
        return SeekerRepository(self._session).get_or_create(user_id)

    def update(
        self,
        user_id: str,
        contact: ContactInfo | None = None,
        intention: JobIntention | None = None,
    ) -> JobSeekerProfile:
        """更新联系方式与求职意向；意向变更后下个拉取周期按新意向执行。

        拉取任务实时读取当前意向，因此更新即联动生效。
        """
        repo = SeekerRepository(self._session)
        profile = repo.get_or_create(user_id)
        if contact is not None:
            if not contact.is_valid():
                raise InvalidParamError("联系方式必须为有效手机号或邮箱")
            profile.contact = contact
        if intention is not None:
            profile.intention = intention
        repo.save(profile)
        self._session.commit()
        logger.info(
            "profile_updated",
            user_id=user_id,
            intention=profile.intention.to_dict(),
        )
        return profile