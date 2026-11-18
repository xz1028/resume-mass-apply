"""全链路集成测试：简历上传→意向配置→授权→职位拉取→筛选→匹配推荐→
黑名单→任务创建→确认→执行→状态同步→通知→统计报告（spec 5.1-5.5 主链路）。"""

import io
from datetime import datetime, timedelta

import fitz

from app.config import DEFAULT_USER_ID
from app.domain.models import DeliveryStatus
from app.infra.notifier import get_notifier
from app.platforms.spi import PositionDTO, StatusReceipt
from app.repositories.repos import RecordRepository
from app.services.delivery_service import build_delivery_service
from app.services.job_service import JobService
from app.services.tracking_service import TrackingService


def make_text_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def setup_positions(mock) -> None:
    now = datetime.now()
    mock.set_positions(
        [
            PositionDTO(
                position_id="p1", platform_id="mock_platform",
                title="Java 开发工程师（3-5年）", company="阿里", city="深圳",
                salary_min=20000, salary_max=35000, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            ),
            PositionDTO(
                position_id="p2", platform_id="mock_platform",
                title="Python 后端工程师", company="腾讯", city="深圳",
                salary_min=18000, salary_max=30000, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            ),
            PositionDTO(
                position_id="p3", platform_id="mock_platform",
                title="销售经理", company="某销售公司", city="上海",
                salary_min=8000, salary_max=12000, industry="销售",
                experience_req="1-3年", publish_expire_at=now + timedelta(days=30),
            ),
        ]
    )


def fetch_positions(test_env) -> dict:
    session = test_env.database.session()
    try:
        return JobService(session, test_env.registry).fetch_positions(DEFAULT_USER_ID)
    finally:
        session.close()


def confirm_and_execute(test_env, task_id: str) -> None:
    session = test_env.database.session()
    try:
        svc = build_delivery_service(session)
        svc.confirm_task(DEFAULT_USER_ID, task_id)
        import asyncio

        asyncio.run(svc.execute_task(task_id))
    finally:
        session.close()


def test_full_flow(client, test_env, reset_notifier):
    mock = test_env.mock

    # 1. 上传简历：首个档案自动默认，默认命名为文件名（spec 5.1.1.1.a）
    pdf = make_text_pdf("Java 后端开发工程师 3年经验 精通 Java Spring MySQL Docker")
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("我的简历.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    resume = resp.json()
    assert resume["name"] == "我的简历.pdf"
    assert resume["is_default"] is True

    # 2. 配置联系方式与求职意向
    resp = client.put(
        "/api/v1/profile",
        json={
            "user_id": DEFAULT_USER_ID,
            "contact": {"phone": "13800138000"},
            "intention": {"city": "深圳", "salary_min": 15000, "salary_max": 30000},
        },
    )
    assert resp.status_code == 200, resp.text

    # 3. 授权平台（凭证加密入库，日志脱敏）
    resp = client.post(
        "/api/v1/platforms/mock_platform/authorization",
        json={"credential": "valid-token"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["auth_status"] == "authorized"

    # 4. 配置职位数据集并拉取
    setup_positions(mock)
    result = fetch_positions(test_env)
    assert result["mock_platform"]["status"] == "ok"
    assert result["mock_platform"]["fetched"] == 3

    # 5. 筛选：城市=深圳、薪资≥15K（spec 5.2.1.2）
    resp = client.get("/api/v1/positions", params={"city": "深圳", "salary_min": 15000})
    data = resp.json()
    assert data["total"] == 2, data
    assert all(i["city"] == "深圳" for i in data["items"])

    # 6. 推荐：按匹配度降序（spec 5.3.1.3）
    resp = client.get("/api/v1/recommendations", params={"top_n": 10})
    data = resp.json()
    assert data["matching_unavailable"] is False
    items = data["items"]
    scores = [i["match_score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    by_id = {i["position_id"]: i for i in items}
    assert by_id["p1"]["match_score"] > by_id["p3"]["match_score"]

    # 7. 黑名单立即生效（spec 5.2.1.4）
    resp = client.post(
        "/api/v1/blacklist", json={"type": "company", "content": "某销售公司"}
    )
    assert resp.status_code == 200
    resp = client.get("/api/v1/recommendations")
    assert all(i["company"] != "某销售公司" for i in resp.json()["items"])

    # 8. 创建投递任务：勾选 2 个职位（spec 5.4.1.1.a）
    resp = client.post("/api/v1/delivery-tasks", json={"position_ids": ["p1", "p2"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    task_id = body["task"]["task_id"]
    assert body["task"]["status"] == "pending_confirm"
    assert body["checklist"]["position_count"] == 2
    assert body["checklist"]["platform_distribution"] == {"mock_platform": 2}
    assert body["checklist"]["resume_name"] == "我的简历.pdf"

    # 9. 确认（先落库后发送）并执行
    confirm_and_execute(test_env, task_id)

    session = test_env.database.session()
    try:
        # 10. 投递记录：全部已投递，联系方式为求职者档案
        records = RecordRepository(session).list_by_task(task_id)
        assert len(records) == 2
        assert all(r.status == DeliveryStatus.delivered for r in records)
        assert all(r.delivered_at is not None for r in records)
        assert len(mock.submitted) == 2
        _position, contact = mock.submitted[0]
        assert contact.phone == "13800138000"

        # 11. 状态同步：企业已查看（spec 5.5.1.2）
        target = records[0]
        ref = target.platform_record_ref
        receipt_time = datetime.now()
        mock.queue_status_receipt(
            ref,
            StatusReceipt(
                record_ref=ref, new_status=DeliveryStatus.viewed,
                receipt_time=receipt_time, receipt_seq=1,
            ),
        )
        tracking = TrackingService(session, test_env.registry, get_notifier())
        result = tracking.sync_status(DEFAULT_USER_ID)
        assert result["synced"] == 1
        session.expire_all()
        updated = RecordRepository(session).get(target.record_id)
        assert updated.status == DeliveryStatus.viewed

        # 幂等：同一回执重复同步不产生第二次状态变更
        mock.queue_status_receipt(
            ref,
            StatusReceipt(
                record_ref=ref, new_status=DeliveryStatus.viewed,
                receipt_time=receipt_time, receipt_seq=1,
            ),
        )
        result = tracking.sync_status(DEFAULT_USER_ID)
        assert result["synced"] == 0
        session.expire_all()
        assert (
            RecordRepository(session).get(target.record_id).status_updated_at
            == updated.status_updated_at
        )

        # 12. 面试邀请 → 通知（spec 5.5.1.3）
        mock.queue_status_receipt(
            ref,
            StatusReceipt(
                record_ref=ref, new_status=DeliveryStatus.interview_invited,
                receipt_time=datetime.now(), receipt_seq=2,
            ),
        )
        tracking.sync_status(DEFAULT_USER_ID)
        session.expire_all()
        assert (
            RecordRepository(session).get(target.record_id).status
            == DeliveryStatus.interview_invited
        )
    finally:
        session.close()

    # 13. 投递记录查询：含简历快照（数据隔离：仅本人）
    resp = client.get("/api/v1/delivery-records")
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["resume_snapshot"]["name"] == "我的简历.pdf"

    # 14. 统计报告（spec 5.5.1.4）
    resp = client.get("/api/v1/delivery-statistics")
    data = resp.json()
    assert data["total"] == 2
    assert data["status_distribution"].get("interview_invited") == 1
    assert data["status_distribution"].get("delivered") == 1
    assert data["platform_distribution"].get("mock_platform") == 2

    # 15. 任务执行摘要（成功数/失败数/跳过数）
    resp = client.get(f"/api/v1/delivery-tasks/{task_id}")
    data = resp.json()
    assert data["status"] == "completed"
    assert data["success_count"] == 2
    assert data["failed_count"] == 0
    assert data["skipped_count"] == 0

    # 16. 监控指标端点可访问且为 Prometheus 格式
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"rma_delivery_attempts_total" in resp.content