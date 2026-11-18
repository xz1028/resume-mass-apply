"""演示模式集成测试（tasks 2.8）：注入/幂等/禁注/清除/续清/API 契约。

红线验证：RMA_DEMO_MODE 默认 off 时 bootstrap 即时返回零影响（142 项测试保护）。
"""

import pytest

from app.config import settings
from app.domain.models import DeliveryStatus
from app.repositories.repos import (
    AuthorizationRepository,
    PositionRepository,
    RecordRepository,
    ResumeRepository,
    SettingRepository,
    TaskRepository,
)
from app.services.demo_mode_service import (
    DEMO_POSITION_PREFIX,
    DEMO_RESUME_NAME,
    DEMO_SEED_TASK_ID,
    DEMO_STATE_KEY,
    DemoModeService,
)


@pytest.fixture
def demo_env(test_env, monkeypatch):
    """独立环境 + demo_mode=auto 门控开启。"""
    monkeypatch.setattr(settings, "demo_mode", "auto")
    return test_env


def _session(test_env):
    return test_env.database.session()


class TestDemoModeBootstrap:
    def test_off_by_default_no_side_effects(self, test_env):
        """默认 off：bootstrap 即时返回，无任何数据写入。"""
        session = _session(test_env)
        try:
            DemoModeService(session).bootstrap()
            assert ResumeRepository(session).list_by_user("local_user") == []
            assert SettingRepository(session).get(DEMO_STATE_KEY) is None
        finally:
            session.close()

    def test_auto_fresh_environment_injects_once(self, demo_env):
        """auto + 空库 → 恰好一份演示数据（简历1/授权1/记录23/跨平台演示职位8）。

        注：conftest 注册的 MockAdapter 为 demo_data=False，授权拉取 0 个 mock 职位；
        585 个演示职位的生成验证由 tests/unit/test_demo_whitelist.py 覆盖。
        """
        session = _session(demo_env)
        try:
            DemoModeService(session).bootstrap()
            assert ResumeRepository(session).list_by_user("local_user")[0].name == DEMO_RESUME_NAME
            assert AuthorizationRepository(session).get("mock_platform") is not None
            records = RecordRepository(session).list_by_task(DEMO_SEED_TASK_ID)
            assert len(records) == 23
            positions, total = PositionRepository(session).list_active(page=1, page_size=100000)
            demo_x = [p for p in positions if p.position_id.startswith(DEMO_POSITION_PREFIX)]
            assert len(demo_x) == 8  # boss 4 + zhilian 4：支撑 23 条记录页完整显示
            assert total == 8  # 测试环境 mock 适配器无演示数据集
            assert DemoModeService(session).is_active() is True
        finally:
            session.close()

    def test_injection_idempotent_on_restart(self, demo_env):
        """注入后重启（再次 bootstrap）不重复。"""
        session = _session(demo_env)
        try:
            service = DemoModeService(session)
            service.bootstrap()
            records_before = len(RecordRepository(session).list_by_task(DEMO_SEED_TASK_ID))
            positions_before, total_before = PositionRepository(session).list_active(page=1, page_size=100000)
            session.close()

            session2 = _session(demo_env)
            DemoModeService(session2).bootstrap()
            records_after = len(RecordRepository(session2).list_by_task(DEMO_SEED_TASK_ID))
            positions_after, total_after = PositionRepository(session2).list_active(page=1, page_size=100000)
            assert records_before == records_after == 23
            assert total_before == total_after
        finally:
            session.close()

    def test_existing_resume_blocks_injection(self, demo_env):
        """已有用户简历时零注入，既有数据原样保留（真实数据保护）。"""
        session = _session(demo_env)
        try:
            from tests.integration.test_full_flow import make_text_pdf

            from app.config import settings as app_settings
            from app.infra.crypto import get_crypto
            from app.services.resume_service import ResumeService

            ResumeService(session, get_crypto(), app_settings.resume_storage_dir).upload(
                "local_user", "我的真实简历.pdf", make_text_pdf("Java 工程师 3 年经验")
            )
            session.close()

            session2 = _session(demo_env)
            DemoModeService(session2).bootstrap()
            resumes = ResumeRepository(session2).list_by_user("local_user")
            assert len(resumes) == 1
            assert resumes[0].name == "我的真实简历.pdf"
            assert RecordRepository(session2).list_by_task(DEMO_SEED_TASK_ID) == []
            assert SettingRepository(session2).get(DEMO_STATE_KEY) is None
        finally:
            session.close()

    def test_record_construction_params(self, demo_env):
        """演示记录构造参数：5 种状态 / 近 7 天 / 3 平台分布 / ref=None 不入同步队列。"""
        session = _session(demo_env)
        try:
            DemoModeService(session).bootstrap()
            records = RecordRepository(session).list_by_task(DEMO_SEED_TASK_ID)
            statuses = {r.status for r in records}
            assert {
                DeliveryStatus.delivered,
                DeliveryStatus.viewed,
                DeliveryStatus.interview_invited,
                DeliveryStatus.rejected,
                DeliveryStatus.failed,
            } <= statuses
            platforms = {r.platform_id for r in records}
            assert {"mock_platform", "boss_zhipin", "zhilian"} <= platforms
            assert all(r.platform_record_ref is None for r in records)
            from datetime import datetime, timedelta

            week_ago = datetime.now() - timedelta(days=7)
            assert all(r.created_at >= week_ago for r in records)
            syncable = RecordRepository(session).list_syncable("local_user")
            assert all(r.task_id != DEMO_SEED_TASK_ID for r in syncable)
        finally:
            session.close()


class TestDemoModeReset:
    def test_reset_clears_demo_data_keeps_authorization(self, demo_env):
        """退出清除：数据归零，模拟平台授权保留。"""
        session = _session(demo_env)
        try:
            service = DemoModeService(session)
            service.bootstrap()
            session.close()

            session2 = _session(demo_env)
            cleared = DemoModeService(session2).reset()
            assert cleared["resumes"] == 1
            assert cleared["records"] == 23
            assert cleared["positions"] == 8
            assert cleared["markers"] == 1
            assert ResumeRepository(session2).list_by_user("local_user") == []
            assert RecordRepository(session2).list_by_task(DEMO_SEED_TASK_ID) == []
            assert TaskRepository(session2).get(DEMO_SEED_TASK_ID) is None
            assert AuthorizationRepository(session2).get("mock_platform") is not None  # 授权保留
            positions, total = PositionRepository(session2).list_active(page=1, page_size=100000)
            assert total == 0  # 测试环境 mock 无演示数据集；跨平台演示职位已清除
        finally:
            session.close()

    def test_reset_idempotent_when_not_active(self, demo_env):
        """非演示态 reset 幂等空操作返回全 0 不报错。"""
        session = _session(demo_env)
        try:
            cleared = DemoModeService(session).reset()
            assert cleared == {"resumes": 0, "records": 0, "positions": 0, "markers": 0}
        finally:
            session.close()

    def test_clearing_state_resumed_on_bootstrap(self, demo_env):
        """清除中断以 clearing 承接：下次启动续清。"""
        session = _session(demo_env)
        try:
            service = DemoModeService(session)
            service.bootstrap()
            session.close()

            session2 = _session(demo_env)
            service2 = DemoModeService(session2)
            service2._set_state("clearing")
            session2.close()

            session3 = _session(demo_env)
            DemoModeService(session3).bootstrap()  # clearing → 续清
            assert ResumeRepository(session3).list_by_user("local_user") == []
            assert RecordRepository(session3).list_by_task(DEMO_SEED_TASK_ID) == []
            assert SettingRepository(session3).get(DEMO_STATE_KEY) is None
        finally:
            session.close()


class TestDemoModeApiContract:
    def test_status_and_reset_via_api(self, demo_env, client):
        """3 个新 API 契约：demo-mode 查询/reset 计数幂等/browser-component。

        显式 bootstrap 注入（TestClient 不以 with 方式使用不触发 lifespan）。
        """
        session = _session(demo_env)
        try:
            DemoModeService(session).bootstrap()
        finally:
            session.close()

        resp = client.get("/api/v1/demo-mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["clearable_summary"]["records"] == 23
        assert data["clearable_summary"]["positions"] == 8

        resp = client.post("/api/v1/demo-mode/reset")
        assert resp.status_code == 200
        assert resp.json()["records"] == 23
        assert resp.json()["positions"] == 8

        resp = client.get("/api/v1/demo-mode")
        assert resp.json()["active"] is False

        # 幂等二次 reset
        resp = client.post("/api/v1/demo-mode/reset")
        assert resp.json() == {"resumes": 0, "records": 0, "positions": 0, "markers": 0}

    def test_browser_component_endpoint(self, client, test_env):
        resp = client.get("/api/v1/platform-access/browser-component")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"available", "reason", "guide"}
        assert isinstance(data["available"], bool)

    def test_demo_mode_default_off_api(self, client, test_env):
        """默认 off：demo-mode 接口返回 inactive 不注入。"""
        resp = client.get("/api/v1/demo-mode")
        assert resp.status_code == 200
        assert resp.json()["active"] is False
        assert resp.json()["clearable_summary"]["resumes"] == 0