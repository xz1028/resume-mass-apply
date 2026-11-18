"""异常场景集成测试：覆盖 spec 5.1-5.5 全部异常场景与 DFX 约束。"""

import asyncio
import io
from datetime import datetime, timedelta

import fitz

import app.services.delivery_service as delivery_service_module
from app.config import DEFAULT_USER_ID, settings
from app.domain.models import DeliveryStatus, JobPosition
from app.infra.notifier import (
    FailingNotificationClient,
    LoggingNotificationClient,
    resend_pending,
    set_notifier,
)
from app.platforms.mock_adapter import (
    SCENARIO_RATE_LIMITED,
    SCENARIO_TIMEOUT,
    SCENARIO_UNAVAILABLE,
)
from app.platforms.spi import PositionDTO, StatusReceipt
from app.repositories.repos import PositionRepository, RecordRepository
from app.services.delivery_service import build_delivery_service
from app.services.job_service import JobService, make_recovery_fetcher
from app.services.tracking_service import TrackingService


def make_text_pdf(text: str = "Java 后端 3年经验") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def setup_env(client, test_env, positions=None) -> None:
    """通用前置：上传简历 + 配置联系方式 + 授权平台 + 拉取职位。"""
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.pdf", io.BytesIO(make_text_pdf()), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        "/api/v1/profile",
        json={
            "user_id": DEFAULT_USER_ID,
            "contact": {"phone": "13800138000"},
            "intention": {"city": "深圳"},
        },
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/v1/platforms/mock_platform/authorization",
        json={"credential": "valid-token"},
    )
    assert resp.status_code == 200, resp.text
    now = datetime.now()
    test_env.mock.set_positions(
        positions
        or [
            PositionDTO(
                position_id="p1", platform_id="mock_platform",
                title="Java 开发工程师", company="A公司", city="深圳",
                salary_min=20000, salary_max=30000, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            ),
            PositionDTO(
                position_id="p2", platform_id="mock_platform",
                title="Python 工程师", company="B公司", city="深圳",
                salary_min=18000, salary_max=28000, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            ),
        ]
    )
    session = test_env.database.session()
    try:
        JobService(session, test_env.registry).fetch_positions(DEFAULT_USER_ID)
    finally:
        session.close()


def create_task(client, position_ids: list[str]) -> str:
    resp = client.post("/api/v1/delivery-tasks", json={"position_ids": position_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]["task_id"]


def confirm_and_execute(test_env, task_id: str) -> None:
    session = test_env.database.session()
    try:
        svc = build_delivery_service(session)
        svc.confirm_task(DEFAULT_USER_ID, task_id)
        asyncio.run(svc.execute_task(task_id))
    finally:
        session.close()


# ---------- 5.1.3 简历上传异常 ----------


def test_upload_rejects_image_format(client, test_env):
    """spec 5.1.1.1.c：图片格式拒绝并提示仅支持 PDF/Word。"""
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("photo.png", io.BytesIO(b"\x89PNG fake"), "image/png")},
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == 40001
    assert "仅支持 PDF 或 Word" in error["message"]


def test_upload_rejects_oversize(client, test_env):
    """spec 5.1.1.1.b：30MB 简历拒绝并提示大小限制。"""
    big = b"%PDF-" + b"0" * (21 * 1024 * 1024)
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
    )
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == 40002
    assert "20MB" in error["message"]


def test_upload_rejects_corrupted_pdf(client, test_env):
    """spec 5.1.3.1：后缀为 PDF 但内容损坏 → 拒绝入库。"""
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("fake.pdf", io.BytesIO(b"not really a pdf"), "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == 40003


def test_multi_version_and_default(client, test_env):
    """spec 5.1.1.2：多版本管理 + 唯一默认 + 重名 40004。"""
    for i in range(3):
        resp = client.post(
            "/api/v1/resumes",
            files={"file": (f"简历{i}.pdf", io.BytesIO(make_text_pdf(f"Java {i}年")), "application/pdf")},
        )
        assert resp.status_code == 200
    resp = client.get("/api/v1/resumes")
    assert len(resp.json()) == 3  # spec 5.1.1.2.a：第 3 个上传成功总数为 3
    resumes = {r["name"]: r for r in resp.json()}

    # spec 5.1.1.2.b：设置档案 B 为默认
    resp = client.put(f"/api/v1/resumes/{resumes['简历1.pdf']['resume_id']}/default")
    assert resp.status_code == 200
    resp = client.get("/api/v1/resumes")
    defaults = [r for r in resp.json() if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "简历1.pdf"

    # 重名返回 40004
    resp = client.patch(
        f"/api/v1/resumes/{resumes['简历0.pdf']['resume_id']}", json={"name": "简历1.pdf"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == 40004


def test_delete_protection_keeps_snapshot(client, test_env):
    """spec 5.1.1.3：删除已被投递引用的档案后，历史记录仍可查看快照。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)

    resp = client.get("/api/v1/resumes")
    resume_id = [r for r in resp.json() if r["is_default"]][0]["resume_id"]
    resp = client.delete(f"/api/v1/resumes/{resume_id}")
    assert resp.status_code == 204

    resp = client.get("/api/v1/delivery-records")
    items = resp.json()["items"]
    assert items[0]["resume_snapshot"]["name"] == "r.pdf"
    assert items[0]["resume_snapshot"]["content_hash"]


# ---------- 5.2.3 职位获取异常 ----------


def test_fetch_failure_keeps_stale_data(client, test_env):
    """spec 5.2.3.1：平台接口失败 → 沿用上次数据并标记未更新。"""
    setup_env(client, test_env)
    resp = client.get("/api/v1/positions")
    assert resp.json()["total"] == 2

    test_env.mock.fetch_scenario = SCENARIO_UNAVAILABLE
    session = test_env.database.session()
    try:
        JobService(session, test_env.registry).fetch_positions(DEFAULT_USER_ID)
    finally:
        session.close()

    resp = client.get("/api/v1/positions")
    data = resp.json()
    assert data["total"] == 2  # 沿用旧数据
    assert "mock_platform" in data["not_updated_platforms"]


def test_empty_filter_suggestion(client, test_env):
    """spec 5.2.3.2：筛选结果为空 → 返回放宽条件建议文案。"""
    setup_env(client, test_env)
    resp = client.get("/api/v1/positions", params={"city": "乌鲁木齐"})
    data = resp.json()
    assert data["total"] == 0
    assert data["suggestion"] is not None
    assert "建议" in data["suggestion"]


def test_expired_position_excluded(client, test_env):
    """spec 5.2.1.5：过期职位不出现在职位池中（软删除）。"""
    setup_env(client, test_env)
    session = test_env.database.session()
    try:
        PositionRepository(session).upsert(
            JobPosition(
                position_id="p_old", platform_id="mock_platform", title="过期职位",
                company="C公司", city="深圳", salary_min=10000, salary_max=20000,
                industry="互联网", experience_req="不限",
                publish_expire_at=datetime.now() - timedelta(days=1),
                fetched_at=datetime.now(), expired=False,
            )
        )
        session.commit()
        JobService(session, test_env.registry).cleanup_expired()
    finally:
        session.close()
    resp = client.get("/api/v1/positions", params={"keyword": "过期职位"})
    assert resp.json()["total"] == 0


# ---------- 5.3.3 匹配降级 ----------


def test_scanned_resume_matching_unavailable(client, test_env):
    """spec 5.3.3.1：扫描件简历 → 跳过匹配、按拉取时间排序、附降级标记。"""
    setup_env(client, test_env)
    doc = fitz.open()
    doc.new_page()
    blank = doc.tobytes()
    doc.close()
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("扫描件.pdf", io.BytesIO(blank), "application/pdf")},
    )
    assert resp.status_code == 200
    resume_id = resp.json()["resume_id"]
    resp = client.put(f"/api/v1/resumes/{resume_id}/default")
    assert resp.status_code == 200

    resp = client.get("/api/v1/recommendations")
    data = resp.json()
    assert data["matching_unavailable"] is True
    assert "无法解析" in data["message"]
    assert len(data["items"]) > 0
    assert all(i["match_score"] is None for i in data["items"])


def test_threshold_gates_auto_apply_scope(client, test_env):
    """spec 5.3.1.2：阈值 60 → 匹配度低于阈值的职位不进入条件圈选范围。"""
    setup_env(client, test_env)
    resp = client.put("/api/v1/matching-settings", json={"auto_apply_threshold": 60})
    assert resp.status_code == 200
    resp = client.put(
        "/api/v1/matching-settings", json={"auto_apply_threshold": 101}
    )
    assert resp.status_code == 422  # 越界 40003

    # 条件圈选 min_match_score=99：全部职位匹配度低于 99 → 无有效职位
    resp = client.post(
        "/api/v1/delivery-tasks",
        json={"filter_condition": {"city": "深圳", "min_match_score": 99}},
    )
    assert resp.status_code in (409, 422, 404)


# ---------- 5.4.3 投递异常 ----------


def test_duplicate_delivery_intercepted(client, test_env):
    """spec 5.4.1.2：10 天前已投递的职位再次投递被拦截并提示投递日期。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)

    resp = client.post("/api/v1/delivery-tasks", json={"position_ids": ["p1"]})
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == 40901
    assert "投递过" in error["message"]


def test_daily_limit_reached(client, test_env):
    """spec 5.4.1.3：上限设 1 后第 2 个投递请求被拒绝。"""
    setup_env(client, test_env)
    resp = client.put("/api/v1/delivery-settings", json={"daily_limit": 1})
    assert resp.status_code == 200
    resp = client.put("/api/v1/delivery-settings", json={"daily_limit": 0})
    assert resp.status_code == 422  # daily_limit >= 1

    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)

    resp = client.post("/api/v1/delivery-tasks", json={"position_ids": ["p2"]})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == 40902


def test_unconfirmed_cancel_produces_no_records(client, test_env):
    """spec 5.4.1.6：确认页取消 → 任务不执行且无任何投递记录。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1", "p2"])
    resp = client.post(f"/api/v1/delivery-tasks/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    session = test_env.database.session()
    try:
        assert RecordRepository(session).list_by_task(task_id) == []
    finally:
        session.close()

    # 已取消任务再确认 → 40903
    resp = client.post(f"/api/v1/delivery-tasks/{task_id}/confirm")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == 40903


def test_auth_revoked_skips_all_deliveries(client, test_env):
    """spec 4.3.3 / 5.4.3.1：撤销授权后投递请求全部被跳过。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1", "p2"])
    resp = client.delete("/api/v1/platforms/mock_platform/authorization")
    assert resp.status_code == 204

    confirm_and_execute(test_env, task_id)
    session = test_env.database.session()
    try:
        records = RecordRepository(session).list_by_task(task_id)
        assert all(r.status == DeliveryStatus.pending for r in records)
    finally:
        session.close()
    assert len(test_env.mock.submitted) == 0

    resp = client.get(f"/api/v1/delivery-tasks/{task_id}")
    assert resp.json()["skipped_count"] == 2

    # 未授权撤销 → 40401
    resp = client.delete("/api/v1/platforms/mock_platform/authorization")
    assert resp.status_code == 404


def test_retry_then_failed(client, test_env, monkeypatch):
    """spec 4.2.1：网络超时重试 2 次后置为投递失败并记录原因。"""
    setup_env(client, test_env)
    monkeypatch.setattr(settings, "retry_backoff_seconds", [0, 0])
    test_env.mock.submit_scenario = SCENARIO_TIMEOUT

    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)
    session = test_env.database.session()
    try:
        records = RecordRepository(session).list_by_task(task_id)
        assert records[0].status == DeliveryStatus.failed
        assert records[0].failure_reason is not None
        assert len(test_env.mock.submitted) == 3  # 1 次初始 + 2 次重试
    finally:
        session.close()


def test_rate_limited_pause_then_continue(client, test_env, monkeypatch):
    """spec 5.4.3.2：平台风控 → 暂停后延后继续执行，其余不受影响。"""
    monkeypatch.setattr(delivery_service_module, "RATE_LIMIT_PAUSE_SECONDS", 0.0)
    setup_env(client, test_env)
    test_env.mock.submit_scenarios_queue = [SCENARIO_RATE_LIMITED]

    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)
    session = test_env.database.session()
    try:
        records = RecordRepository(session).list_by_task(task_id)
        assert records[0].status == DeliveryStatus.delivered  # 暂停后重试成功
        assert len(test_env.mock.submitted) == 2
    finally:
        session.close()


def test_cancel_during_execution(client, test_env):
    """spec 5.4.3.3：执行中取消 → 停止发送、已投递保留、摘要正确。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1", "p2"])
    session = test_env.database.session()
    try:
        svc = build_delivery_service(session)
        svc.confirm_task(DEFAULT_USER_ID, task_id)
        result = svc.cancel_task(DEFAULT_USER_ID, task_id)  # executing 状态取消
        assert result["delivered"] == 0

        asyncio.run(svc.execute_task(task_id))  # 感知取消标志，停止发送
        records = RecordRepository(session).list_by_task(task_id)
        assert all(r.status == DeliveryStatus.pending for r in records)
        assert len(test_env.mock.submitted) == 0
    finally:
        session.close()

    resp = client.get(f"/api/v1/delivery-tasks/{task_id}")
    data = resp.json()
    assert data["status"] == "cancelled"
    assert data["success_count"] == 0


def test_filter_condition_task(client, test_env):
    """spec 5.4.1.1.b：按筛选条件圈选生成任务。"""
    setup_env(client, test_env)
    resp = client.post(
        "/api/v1/delivery-tasks",
        json={"filter_condition": {"city": "深圳", "min_match_score": 0}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task"]["status"] == "pending_confirm"
    assert body["checklist"]["position_count"] == 2


# ---------- 5.5.3 状态同步异常 ----------


def test_notification_failure_does_not_block(client, test_env, reset_notifier):
    """通知服务不可用：状态更新主流程不受影响，通知入队暂存后重发。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)

    set_notifier(FailingNotificationClient())
    session = test_env.database.session()
    try:
        records = RecordRepository(session).list_by_task(task_id)
        ref = records[0].platform_record_ref
        test_env.mock.queue_status_receipt(
            ref,
            StatusReceipt(
                record_ref=ref, new_status=DeliveryStatus.interview_invited,
                receipt_time=datetime.now(), receipt_seq=1,
            ),
        )
        tracking = TrackingService(session, test_env.registry, reset_notifier._notifier)
        result = tracking.sync_status(DEFAULT_USER_ID)
        assert result["synced"] == 1  # 状态更新成功（主流程不受影响）
        session.expire_all()
        assert (
            RecordRepository(session).get(records[0].record_id).status
            == DeliveryStatus.interview_invited
        )
        assert len(reset_notifier._pending_events) == 1  # 通知入队暂存

        set_notifier(LoggingNotificationClient())
        sent = resend_pending(reset_notifier._notifier)
        assert sent == 1
        assert len(reset_notifier._pending_events) == 0
    finally:
        session.close()


def test_platform_degrade_and_recover(client, test_env):
    """spec 4.2.3：连续 3 次失败降级为仅职位浏览，恢复后自动补拉。"""
    setup_env(client, test_env)
    registry = test_env.registry
    registry.on_recovery(make_recovery_fetcher(registry))

    for _ in range(3):
        registry.record_call_failure("mock_platform")
    assert registry.is_degraded("mock_platform") is True

    resp = client.get("/api/v1/platforms")
    platform = [p for p in resp.json() if p["platform_id"] == "mock_platform"][0]
    assert platform["degraded"] is True

    # 降级平台跳过拉取
    session = test_env.database.session()
    try:
        result = JobService(session, registry).fetch_positions(DEFAULT_USER_ID)
        assert result["mock_platform"]["status"] == "skipped"
    finally:
        session.close()

    # 平台新增职位后恢复探测成功 → 自动补拉
    now = datetime.now()
    test_env.mock.set_positions(
        [
            PositionDTO(
                position_id="p_new", platform_id="mock_platform",
                title="Go 开发工程师", company="D公司", city="深圳",
                salary_min=20000, salary_max=30000, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            ),
        ]
    )
    registry.record_call_success("mock_platform")
    assert registry.is_degraded("mock_platform") is False

    resp = client.get("/api/v1/positions", params={"keyword": "Go"})
    assert resp.json()["total"] == 1  # 恢复后自动补拉生效


def test_audit_logs_recorded(client, test_env):
    """spec 4.3.4：授权、撤销、发起批量投递、确认投递均记录审计日志。"""
    setup_env(client, test_env)
    task_id = create_task(client, ["p1"])
    confirm_and_execute(test_env, task_id)
    client.delete("/api/v1/platforms/mock_platform/authorization")

    session = test_env.database.session()
    try:
        from app.repositories.orm import AuditLogRow

        actions = {
            row.action
            for row in session.query(AuditLogRow).all()
        }
        assert {
            "authorize",
            "revoke_authorization",
            "create_delivery_task",
            "confirm_delivery_task",
        } <= actions
    finally:
        session.close()