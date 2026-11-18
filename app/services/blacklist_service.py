"""投递黑名单管理：增删查与过滤规则（推荐与投递共用）。

公司类型按全名精确匹配，关键词类型按职位名称包含匹配；
加入后立即对后续所有职位推荐与投递任务生效。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.v1.errors import InvalidParamError, NotFoundError
from app.domain.models import BlacklistEntry, BlacklistType, JobPosition
from app.infra.logging import get_logger
from app.repositories.repos import BlacklistRepository, new_id

logger = get_logger("blacklist_service")


class BlacklistService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user_id: str, entry_type: str, content: str) -> BlacklistEntry:
        try:
            bl_type = BlacklistType(entry_type)
        except ValueError as exc:
            raise InvalidParamError("黑名单类型必须为 company 或 keyword") from exc
        content = (content or "").strip()
        if not content:
            raise InvalidParamError("黑名单内容不能为空")
        existing = self._find_same(user_id, bl_type, content)
        if existing is not None:
            return existing
        entry = BlacklistRepository(self._session).add(
            BlacklistEntry(
                entry_id=new_id("bl_"),
                user_id=user_id,
                type=bl_type,
                content=content,
            )
        )
        self._session.commit()
        logger.info("blacklist_added", user_id=user_id, type=bl_type.value, content=content)
        return entry

    def list(self, user_id: str) -> list[BlacklistEntry]:
        return BlacklistRepository(self._session).list_by_user(user_id)

    def delete(self, user_id: str, entry_id: str) -> None:
        try:
            BlacklistRepository(self._session).delete(user_id, entry_id)
        except LookupError as exc:
            raise NotFoundError(str(exc)) from exc
        self._session.commit()
        logger.info("blacklist_removed", user_id=user_id, entry_id=entry_id)

    def _find_same(self, user_id: str, bl_type: BlacklistType, content: str) -> BlacklistEntry | None:
        for entry in self.list(user_id):
            if entry.type == bl_type and entry.content == content:
                return entry
        return None

    @staticmethod
    def is_blacklisted(
        position: JobPosition, entries: list[BlacklistEntry]
    ) -> bool:
        for entry in entries:
            if entry.type == BlacklistType.company and position.company == entry.content:
                return True
            if entry.type == BlacklistType.keyword and entry.content in position.title:
                return True
        return False

    @staticmethod
    def split(entries: list[BlacklistEntry]) -> tuple[list[str], list[str]]:
        companies = [e.content for e in entries if e.type == BlacklistType.company]
        keywords = [e.content for e in entries if e.type == BlacklistType.keyword]
        return companies, keywords