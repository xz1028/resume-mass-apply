"""简历档案管理服务：上传校验、多版本管理、默认简历、删除保护、解密读取。"""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.api.v1.errors import (
    DuplicateResumeNameAPIError,
    FileTooLargeError,
    InvalidParamError,
    NotFoundError,
    UnsupportedFormatError,
)
from app.config import settings
from app.domain.models import (
    DuplicateResumeNameError,
    ResumeFormat,
    ResumeProfile,
    ResumeSnapshot,
)
from app.infra.crypto import CryptoService
from app.infra.logging import get_logger
from app.repositories.repos import (
    RecordRepository,
    ResumeRepository,
    TaskRepository,
    new_id,
)

logger = get_logger("resume_service")

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _is_structurally_valid(fmt: str, content: bytes) -> bool:
    """魔数/结构探测：拒绝后缀正确但内容损坏的文件。"""
    if fmt == "pdf":
        return content.startswith(PDF_MAGIC)
    if fmt == "docx":
        return content.startswith(ZIP_MAGIC)
    if fmt == "doc":
        return content.startswith(OLE2_MAGIC)
    return False


class ResumeService:
    def __init__(self, session: Session, crypto: CryptoService, storage_dir: Path) -> None:
        self._session = session
        self._crypto = crypto
        self._storage_dir = Path(storage_dir)

    def upload(self, user_id: str, filename: str, content: bytes) -> ResumeProfile:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in settings.resume_allowed_formats:
            raise UnsupportedFormatError("仅支持 PDF 或 Word 格式")
        if len(content) > settings.resume_max_size_mb * 1024 * 1024:
            raise FileTooLargeError(f"文件大小超过限制（{settings.resume_max_size_mb}MB）")
        if not _is_structurally_valid(ext, content):
            raise InvalidParamError("文件无法识别，请确认文件完整性后重新上传")

        repo = ResumeRepository(self._session)
        name = filename
        seq = 2
        while repo.exists_name(user_id, name):
            stem = Path(filename).stem
            name = f"{stem} ({seq}){Path(filename).suffix}"
            seq += 1

        resume_id = new_id("resume_")
        storage_ref = f"{user_id}/{resume_id}.enc"
        encrypted = self._crypto.encrypt(content)
        file_path = self._storage_dir / storage_ref
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(encrypted)

        is_first = len(repo.list_by_user(user_id)) == 0
        created = repo.add(
            ResumeProfile(
                resume_id=resume_id,
                user_id=user_id,
                name=name,
                format=ResumeFormat(ext),
                size_bytes=len(content),
                is_default=is_first,
                created_at=datetime.now(),
                storage_ref=storage_ref,
            )
        )
        self._session.commit()
        logger.info(
            "resume_uploaded",
            resume_id=resume_id,
            name=name,
            size_bytes=len(content),
            is_default=is_first,
        )
        return created

    def list(self, user_id: str) -> list[ResumeProfile]:
        return ResumeRepository(self._session).list_by_user(user_id)

    def rename(self, user_id: str, resume_id: str, name: str) -> ResumeProfile:
        repo = ResumeRepository(self._session)
        try:
            updated = repo.rename(user_id, resume_id, name)
            self._session.commit()
            return updated
        except LookupError as exc:
            raise NotFoundError(str(exc)) from exc
        except DuplicateResumeNameError as exc:
            raise DuplicateResumeNameAPIError(f"简历档案名称已存在: {name}") from exc

    def set_default(self, user_id: str, resume_id: str) -> ResumeProfile:
        repo = ResumeRepository(self._session)
        try:
            updated = repo.set_default(user_id, resume_id)
            self._session.commit()
            logger.info("default_resume_set", user_id=user_id, resume_id=resume_id)
            return updated
        except LookupError as exc:
            raise NotFoundError(str(exc)) from exc

    def delete(self, user_id: str, resume_id: str) -> None:
        """删除保护：单事务内先将快照固化到引用过该档案的历史投递记录，再删除档案。"""
        repo = ResumeRepository(self._session)
        resume = repo.get(user_id, resume_id)
        if resume is None:
            raise NotFoundError(f"简历档案不存在: {resume_id}")
        _, content = self.get_decrypted(user_id, resume_id)
        snapshot = self._snapshot_of(resume, content)
        self._solidify_snapshots(user_id, resume, snapshot)
        storage_ref = resume.storage_ref
        repo.delete(user_id, resume_id)
        self._session.commit()
        (self._storage_dir / storage_ref).unlink(missing_ok=True)
        logger.info("resume_deleted", resume_id=resume_id)

    def _solidify_snapshots(self, user_id: str, resume: ResumeProfile, snapshot: ResumeSnapshot) -> None:
        task_repo = TaskRepository(self._session)
        record_repo = RecordRepository(self._session)
        for task in task_repo.list_by_resume(user_id, resume.resume_id):
            for record in record_repo.list_by_task(task.task_id):
                if record.resume_snapshot is None:
                    record_repo.update_snapshot(record.record_id, snapshot)

    @staticmethod
    def _snapshot_of(resume: ResumeProfile, content: bytes) -> ResumeSnapshot:
        return ResumeSnapshot(
            name=resume.name,
            format=resume.format.value,
            content_hash=hashlib.sha256(content).hexdigest(),
            created_at=resume.created_at,
        )

    def get_decrypted(self, user_id: str, resume_id: str) -> tuple[ResumeProfile, bytes]:
        """解密读取简历原始内容（供投递引擎与文本提取使用）。"""
        resume = ResumeRepository(self._session).get(user_id, resume_id)
        if resume is None:
            raise NotFoundError(f"简历档案不存在: {resume_id}")
        encrypted = (self._storage_dir / resume.storage_ref).read_bytes()
        return resume, self._crypto.decrypt(encrypted)

    def snapshot_for_delivery(self, user_id: str, resume_id: str) -> tuple[ResumeProfile, bytes, ResumeSnapshot]:
        """投递用：返回档案、解密内容与投递快照（创建投递记录时固化）。"""
        resume, content = self.get_decrypted(user_id, resume_id)
        return resume, content, self._snapshot_of(resume, content)