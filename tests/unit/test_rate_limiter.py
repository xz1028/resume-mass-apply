"""令牌桶限流器单元测试：速率边界与每日上限口径。"""

from app.infra.rate_limiter import RateLimiterRegistry, TokenBucket


def test_burst_within_capacity() -> None:
    """容量 1：首次立即获得令牌，第二次必须等待。"""
    bucket = TokenBucket(max_per_hour=10)
    assert bucket.wait_time() == 0.0
    assert bucket.wait_time() > 0.0


def test_wait_time_reasonable() -> None:
    """3600/小时 = 1 次/秒：耗尽令牌后下一次需等待约 1 秒。"""
    bucket = TokenBucket(max_per_hour=3600)
    assert bucket.wait_time() == 0.0
    wait = bucket.wait_time()
    assert 0.0 < wait <= 1.0


def test_hourly_rate_never_exceeded() -> None:
    """30 次/小时：等待时间约 120 秒，任意窗口内速率不超限。"""
    bucket = TokenBucket(max_per_hour=30)
    assert bucket.wait_time() == 0.0
    wait = bucket.wait_time()
    assert 100.0 < wait <= 120.0


def test_tokens_refill_over_time() -> None:
    import time

    bucket = TokenBucket(max_per_hour=36000)  # 10/s
    bucket.wait_time()
    time.sleep(0.15)
    assert bucket.tokens > 0


def test_registry_uses_platform_policy() -> None:
    registry = RateLimiterRegistry({"mock_platform": 100000.0})
    assert registry.wait_time("mock_platform") == 0.0


def test_registry_default_policy_for_unknown_platform() -> None:
    registry = RateLimiterRegistry({})
    assert registry.wait_time("unknown") == 0.0  # 默认 30/h，容量 1，首次可用
    assert registry.wait_time("unknown") > 0.0


def test_daily_limit_counting_logic() -> None:
    """每日上限按自然日统计当日创建的投递记录数（见 RecordRepository.count_today）。"""
    from datetime import datetime

    from app.infra.database import Database
    from app.domain.models import DeliveryRecord, DeliveryStatus, ResumeSnapshot
    from app.repositories.repos import RecordRepository, new_id

    database = Database("sqlite://")
    database.create_all()
    session = database.session()
    repo = RecordRepository(session)
    snapshot = ResumeSnapshot(name="r", format="pdf", content_hash="h",
                              created_at=datetime(2026, 1, 1))
    now = datetime.now()
    for i in range(3):
        repo.add(DeliveryRecord(
            record_id=new_id("rec_"), user_id="u1", task_id="t1",
            position_id=f"p{i}", platform_id="mock_platform",
            status=DeliveryStatus.pending, created_at=now, status_updated_at=now,
            resume_snapshot=snapshot,
        ))
    assert repo.count_today("u1") == 3
    assert repo.count_today("u1", now=now.replace(hour=0, minute=0, second=1)) == 3
    # 其他用户不受影响
    assert repo.count_today("u2") == 0
    session.close()