"""校验规则单元测试：联系方式、文件结构探测、黑名单过滤、档案命名约束。"""

from datetime import datetime

import pytest

from app.domain.models import (
    BlacklistEntry,
    BlacklistType,
    ContactInfo,
    DeliveryStatus,
    DeliveryRecord,
    DuplicateResumeNameError,
    JobPosition,
    ResumeFormat,
    ResumeProfile,
    ResumeSnapshot,
)
from app.infra.database import Database
from app.repositories.repos import RecordRepository, ResumeRepository, new_id
from app.services.blacklist_service import BlacklistService
from app.services.resume_service import _is_structurally_valid


def test_contact_info_validation() -> None:
    assert ContactInfo(phone="13800138000").is_valid() is True
    assert ContactInfo(email="user@example.com").is_valid() is True
    assert ContactInfo(phone="13800138000", email="user@example.com").is_valid() is True
    assert ContactInfo(phone="12345").is_valid() is False
    assert ContactInfo(phone="1380013800").is_valid() is False  # 10 位不足
    assert ContactInfo(email="invalid-email").is_valid() is False
    assert ContactInfo().is_valid() is False


def test_structural_validation_magic_numbers() -> None:
    assert _is_structurally_valid("pdf", b"%PDF-1.7 rest") is True
    assert _is_structurally_valid("pdf", b"\x89PNG fake") is False
    assert _is_structurally_valid("docx", b"PK\x03\x04 zip") is True
    assert _is_structurally_valid("docx", b"%PDF-1.7") is False
    assert _is_structurally_valid("doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1ole") is True
    assert _is_structurally_valid("txt", b"anything") is False


def _position(**overrides) -> JobPosition:
    base = dict(
        position_id="p1",
        platform_id="mock_platform",
        title="Java 开发工程师",
        company="X公司",
        city="深圳",
        salary_min=20000,
        salary_max=30000,
        industry="互联网",
        experience_req="3-5年",
        publish_expire_at=datetime(2099, 1, 1),
        fetched_at=datetime.now(),
    )
    base.update(overrides)
    return JobPosition(**base)


def test_blacklist_company_exact_match() -> None:
    entries = [BlacklistEntry("e1", "u", BlacklistType.company, "X公司")]
    assert BlacklistService.is_blacklisted(_position(), entries) is True
    assert BlacklistService.is_blacklisted(_position(company="X公司分部"), entries) is False


def test_blacklist_keyword_contains_match() -> None:
    entries = [BlacklistEntry("e1", "u", BlacklistType.keyword, "销售")]
    assert BlacklistService.is_blacklisted(_position(title="销售经理"), entries) is True
    assert BlacklistService.is_blacklisted(_position(title="Java 开发工程师"), entries) is False


def test_blacklist_no_entries_passes() -> None:
    assert BlacklistService.is_blacklisted(_position(), []) is False


def test_resume_name_unique_constraint() -> None:
    database = Database("sqlite://")
    database.create_all()
    session = database.session()
    repo = ResumeRepository(session)
    now = datetime.now()

    def add(name: str) -> ResumeProfile:
        return repo.add(ResumeProfile(
            resume_id=new_id("resume_"), user_id="u1", name=name,
            format=ResumeFormat.pdf, size_bytes=100, is_default=False,
            created_at=now, storage_ref="u1/x.enc",
        ))

    add("简历A")
    with pytest.raises(DuplicateResumeNameError):
        add("简历A")
    add("简历B")  # 不同名 OK
    # 不同用户可同名
    repo.add(ResumeProfile(
        resume_id=new_id("resume_"), user_id="u2", name="简历A",
        format=ResumeFormat.pdf, size_bytes=100, is_default=False,
        created_at=now, storage_ref="u2/x.enc",
    ))
    session.close()


def test_single_default_resume_constraint() -> None:
    database = Database("sqlite://")
    database.create_all()
    session = database.session()
    repo = ResumeRepository(session)
    now = datetime.now()
    ids = []
    for i in range(3):
        r = repo.add(ResumeProfile(
            resume_id=new_id("resume_"), user_id="u1", name=f"简历{i}",
            format=ResumeFormat.pdf, size_bytes=100, is_default=(i == 0),
            created_at=now, storage_ref=f"u1/{i}.enc",
        ))
        ids.append(r.resume_id)
    repo.set_default("u1", ids[1])
    defaults = [r for r in repo.list_by_user("u1") if r.is_default]
    assert len(defaults) == 1
    assert defaults[0].resume_id == ids[1]
    session.close()


def test_recent_delivered_lookup_30_days() -> None:
    from datetime import timedelta

    database = Database("sqlite://")
    database.create_all()
    session = database.session()
    repo = RecordRepository(session)
    snapshot = ResumeSnapshot(name="r", format="pdf", content_hash="h", created_at=datetime.now())
    now = datetime.now()
    record = DeliveryRecord(
        record_id=new_id("rec_"), user_id="u1", task_id="t1",
        position_id="p1", platform_id="mock_platform",
        status=DeliveryStatus.delivered, created_at=now - timedelta(days=10),
        status_updated_at=now, resume_snapshot=snapshot,
        delivered_at=now - timedelta(days=10),
    )
    repo.add(record)
    # 10 天内已投递 → 查到
    found = repo.find_recent_delivered("u1", "p1")
    assert found is not None
    # 40 天前投递 → 超出 30 天窗口，不再拦截
    from app.repositories.orm import DeliveryRecordRow

    session.query(DeliveryRecordRow).filter(
        DeliveryRecordRow.record_id == record.record_id
    ).update({"delivered_at": now - timedelta(days=40)})
    session.flush()
    assert repo.find_recent_delivered("u1", "p1") is None
    session.close()