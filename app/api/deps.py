"""FastAPI 依赖注入：会话、当前用户与服务工厂。

单求职者本地软件：当前用户固定为 local_user，数据模型仍保留 user_id 以隔离数据。
"""

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import DEFAULT_USER_ID, settings
from app.infra.crypto import get_crypto
from app.infra.database import get_database
from app.infra.notifier import get_notifier
from app.platforms.registry import get_registry
from app.services.authorization_service import AuthorizationService
from app.services.blacklist_service import BlacklistService
from app.services.delivery_service import DeliveryService, build_delivery_service
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.profile_service import ProfileService
from app.services.resume_service import ResumeService
from app.services.tracking_service import TrackingService

DEFAULT_USER_ID = DEFAULT_USER_ID  # re-export


def get_session() -> Generator[Session, None, None]:
    session = get_database().session()
    try:
        yield session
    finally:
        session.close()


def get_current_user_id() -> str:
    return DEFAULT_USER_ID


def get_authorization_service(
    session: Session = Depends(get_session),
) -> AuthorizationService:
    return AuthorizationService(session, get_crypto(), get_registry())


def get_resume_service(session: Session = Depends(get_session)) -> ResumeService:
    return ResumeService(session, get_crypto(), settings.resume_storage_dir)

def get_profile_service(session: Session = Depends(get_session)) -> ProfileService:
    return ProfileService(session)


def get_blacklist_service(session: Session = Depends(get_session)) -> BlacklistService:
    return BlacklistService(session)


def get_job_service(session: Session = Depends(get_session)) -> JobService:
    return JobService(session, get_registry())

def get_matching_service(session: Session = Depends(get_session)) -> MatchingService:
    return MatchingService(session, get_resume_service(session))

def get_delivery_service(session: Session = Depends(get_session)) -> DeliveryService:
    return build_delivery_service(session)


def get_tracking_service(session: Session = Depends(get_session)) -> TrackingService:
    return TrackingService(session, get_registry(), get_notifier())