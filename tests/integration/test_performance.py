"""性能验证测试（spec 4.1）：
- 100 职位批量投递完成时间 ≤10 分钟（4.1.1）
- 单职位匹配度计算 ≤2 秒（4.1.2）
- 500 职位推荐列表生成 ≤5 秒（4.1.3）
"""

import asyncio
import time
from datetime import datetime, timedelta

from app.config import DEFAULT_USER_ID
from app.domain.models import DeliveryStatus, JobIntention
from app.matching.engine import WeightedFactorEngine
from app.parsers.resume_parser import ResumeMatchProfile
from app.platforms.spi import PositionDTO
from app.repositories.repos import RecordRepository
from app.services.delivery_service import build_delivery_service
from app.services.job_service import JobService
from tests.integration.test_error_scenarios import setup_env


def test_performance_targets(client, test_env):
    setup_env(client, test_env)
    now = datetime.now()

    # ---- 4.1.3：500 职位推荐列表 ≤5 秒 ----
    test_env.mock.set_positions(
        [
            PositionDTO(
                position_id=f"perf{i}", platform_id="mock_platform",
                title=f"Java 开发工程师 {i}", company=f"公司{i}", city="深圳",
                salary_min=15000 + i, salary_max=25000 + i, industry="互联网",
                experience_req="3-5年", publish_expire_at=now + timedelta(days=30),
            )
            for i in range(500)
        ]
    )
    session = test_env.database.session()
    try:
        JobService(session, test_env.registry).fetch_positions(DEFAULT_USER_ID)
    finally:
        session.close()

    start = time.monotonic()
    resp = client.get("/api/v1/recommendations", params={"top_n": 500})
    recommend_elapsed = time.monotonic() - start
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 500
    assert recommend_elapsed <= 5.0, f"500 职位推荐耗时 {recommend_elapsed:.2f}s 超标"

    # ---- 4.1.2：单职位匹配度计算 ≤2 秒 ----
    engine = WeightedFactorEngine(intention=JobIntention(city="深圳", salary_min=15000))
    resume = ResumeMatchProfile(raw_text="Java", skills={"java"}, years_of_experience=3.0)
    position = PositionDTO(
        position_id="x", platform_id="mock_platform", title="Java 开发工程师",
        company="A", city="深圳", salary_min=20000, salary_max=30000,
        industry="互联网", experience_req="3-5年", publish_expire_at=now,
    )
    start = time.monotonic()
    for _ in range(100):
        engine.compute_score(resume, position)
    per_call = (time.monotonic() - start) / 100
    assert per_call <= 2.0, f"单职位匹配计算 {per_call:.4f}s 超标"

    # ---- 4.1.1：100 职位批量投递 ≤10 分钟 ----
    position_ids = [f"perf{i}" for i in range(100)]
    resp = client.post("/api/v1/delivery-tasks", json={"position_ids": position_ids})
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task"]["task_id"]

    start = time.monotonic()
    session = test_env.database.session()
    try:
        svc = build_delivery_service(session)
        svc.confirm_task(DEFAULT_USER_ID, task_id)
        asyncio.run(svc.execute_task(task_id))
    finally:
        session.close()
    delivery_elapsed = time.monotonic() - start
    assert delivery_elapsed <= 600.0, f"100 职位投递耗时 {delivery_elapsed:.2f}s 超标"

    session = test_env.database.session()
    try:
        records = RecordRepository(session).list_by_task(task_id)
        assert len(records) == 100
        assert all(r.status == DeliveryStatus.delivered for r in records)
    finally:
        session.close()

    print(
        f"\n[性能实测] 500 职位推荐: {recommend_elapsed:.2f}s (≤5s) | "
        f"单职位匹配: {per_call * 1000:.2f}ms (≤2s) | "
        f"100 职位投递: {delivery_elapsed:.2f}s (≤600s)"
    )