"""真实平台接入治理单元测试：门禁/启停/限流/挑战流转/风险事件/选择器/风控归类/凭证。"""

import pytest
from datetime import datetime, timedelta

from app.platforms.mock_adapter import MockAdapter
from app.real_platform.access.repositories import (
    AccessConfigRepository,
    CaptchaChallengeRepository,
    RiskEventRepository,
)
from app.real_platform.access.service import PlatformAccessService
from app.real_platform.browser import risk as risk_detector
from app.real_platform.browser.captcha import gate_check, open_challenge
from app.real_platform.browser.selectors import SelectorGroup, try_locate
from app.real_platform.browser.state_store import (
    credential_to_storage_state,
    storage_state_to_credential,
)
from app.api.v1.errors import (
    PlatformAlreadyAuthorizedError,
    RatePolicyExceededError,
    RiskUnconfirmedError,
)
from app.platforms.spi import (
    PlatformAuthExpiredError,
    PlatformRateLimitedError,
    PlatformUnavailableError,
)


@pytest.fixture
def env(test_env):
    """复用既有测试环境（独立数据库+注册表+密钥）。"""
    from app.real_platform.access.repositories import AccessConfigRepository

    session = test_env.database.session()
    repo = AccessConfigRepository(session)
    repo.ensure_preset(
        platform_id="boss_zhipin",
        name="BOSS直聘",
        access_mode="browser_automation",
        priority="P0",
        access_mode_note="测试",
        delivery_rate_per_hour=20.0,
        fetch_interval_hours=12,
    )
    session.commit()
    yield test_env, session
    session.close()


class TestRegistryExtensions:
    """9.3 注册表扩展：重复标识拒绝 + unregister 成员移除。"""

    def test_register_conflict_rejected(self, test_env):
        registry = test_env.registry
        adapter_a = MockAdapter(platform_id="dup_platform")
        adapter_b = MockAdapter(platform_id="dup_platform")
        registry.register(adapter_a)
        with pytest.raises(RuntimeError, match="平台标识冲突"):
            registry.register(adapter_b)
        assert registry.get("dup_platform") is adapter_a

    def test_register_same_instance_idempotent(self, test_env):
        registry = test_env.registry
        adapter = MockAdapter(platform_id="same_platform")
        registry.register(adapter)
        registry.register(adapter)  # 同实例幂等
        assert registry.get("same_platform") is adapter

    def test_unregister_removes_member(self, test_env):
        registry = test_env.registry
        adapter = MockAdapter(platform_id="tmp_platform")
        registry.register(adapter)
        assert registry.unregister("tmp_platform") is True
        assert registry.get("tmp_platform") is None
        assert "tmp_platform" not in dict(registry.list_all())
        assert registry.unregister("tmp_platform") is False  # 幂等

    def test_unregister_clears_degraded_state(self, test_env):
        registry = test_env.registry
        adapter = MockAdapter(platform_id="dg_platform")
        registry.register(adapter)
        registry.mark_degraded("dg_platform")
        registry.unregister("dg_platform")
        assert registry.is_degraded("dg_platform") is False


class TestAccessGovernance:
    """9.1 治理与门禁。"""

    def test_enable_requires_risk_confirmation(self, env):
        test_env, session = env
        svc = PlatformAccessService(session, test_env.registry)
        with pytest.raises(RiskUnconfirmedError):
            svc.enable("boss_zhipin")

    def test_risk_confirm_then_enable(self, env):
        test_env, session = env
        svc = PlatformAccessService(session, test_env.registry)
        svc.confirm_risk("boss_zhipin")
        result = svc.enable("boss_zhipin")
        assert result["enabled"] is True
        assert test_env.registry.get("boss_zhipin") is not None
        assert test_env.registry.get("boss_zhipin").platform_id == "boss_zhipin"
        # 启用幂等
        assert svc.enable("boss_zhipin")["enabled"] is True

    def test_risk_confirmation_persists_after_enable(self, env):
        """已确认但未启用的场景：再次启用直接进入启用操作。"""
        test_env, session = env
        svc = PlatformAccessService(session, test_env.registry)
        svc.confirm_risk("boss_zhipin")
        config = svc.get_config("boss_zhipin")
        assert config["risk_confirmed"] is True

    def test_disable_unregisters_and_keeps_history(self, env):
        test_env, session = env
        svc = PlatformAccessService(session, test_env.registry)
        svc.confirm_risk("boss_zhipin")
        svc.enable("boss_zhipin")
        result = svc.disable("boss_zhipin")
        assert result["enabled"] is False
        assert test_env.registry.get("boss_zhipin") is None
        # 幂等
        assert svc.disable("boss_zhipin")["enabled"] is False

    def test_rate_policy_upper_bound(self, env):
        test_env, session = env
        svc = PlatformAccessService(session, test_env.registry)
        svc.confirm_risk("boss_zhipin")
        with pytest.raises(RatePolicyExceededError):
            svc.update_rate_policy("boss_zhipin", 31.0)
        with pytest.raises(RatePolicyExceededError):
            svc.update_rate_policy("boss_zhipin", 0)
        result = svc.update_rate_policy("boss_zhipin", 25.0)
        assert result["delivery_rate_per_hour"] == 25.0

    def test_single_account_boundary(self, env):
        test_env, session = env
        from app.domain.models import AuthStatus, PlatformAuthorization
        from app.repositories.repos import AuthorizationRepository

        AuthorizationRepository(session).upsert(
            PlatformAuthorization(
                platform_id="boss_zhipin",
                user_id="local_user",
                credential_cipher=b"x",
                status=AuthStatus.authorized,
                authorized_at=datetime.now(),
            )
        )
        session.commit()
        svc = PlatformAccessService(session, test_env.registry)
        with pytest.raises(PlatformAlreadyAuthorizedError):
            svc.ensure_no_existing_authorization("boss_zhipin")
        assert svc.credential_exists("boss_zhipin") is True


class TestCaptchaRepositories:
    """挑战状态流转幂等与归档清理边界。"""

    def test_challenge_lifecycle_idempotent(self, env):
        test_env, session = env
        repo = CaptchaChallengeRepository(session)
        row = repo.create("boss_zhipin", "delivery", 600)
        assert repo.find_pending("boss_zhipin") is not None
        assert repo.complete(row.challenge_id) is True
        assert repo.complete(row.challenge_id) is False  # 幂等：重复 complete 不变更
        assert repo.expire(row.challenge_id) is False  # 终态不可再流转
        session.rollback()

    def test_challenge_expire_idempotent(self, env):
        test_env, session = env
        repo = CaptchaChallengeRepository(session)
        row = repo.create("zhilian", "fetch", 600)
        assert repo.expire(row.challenge_id) is True
        assert repo.expire(row.challenge_id) is False
        session.rollback()

    def test_overdue_expired_unblocks_gate(self, env):
        test_env, session = env
        repo = CaptchaChallengeRepository(session)
        row = repo.create("job51", "delivery", 1)
        # 手动回拨过期时间
        from app.real_platform.access.models import CaptchaChallengeRow

        session.query(CaptchaChallengeRow).filter(
            CaptchaChallengeRow.challenge_id == row.challenge_id
        ).update({"expires_at": datetime.now() - timedelta(seconds=5)})
        session.flush()
        count = repo.expire_all_overdue("job51")
        assert count == 1
        assert repo.find_pending("job51") is None  # 门闸解除
        session.rollback()

    def test_archive_terminal_30_days(self, env):
        test_env, session = env
        repo = CaptchaChallengeRepository(session)
        row = repo.create("boss_zhipin", "login", 60)
        repo.complete(row.challenge_id)
        from app.real_platform.access.models import CaptchaChallengeRow

        session.query(CaptchaChallengeRow).filter(
            CaptchaChallengeRow.challenge_id == row.challenge_id
        ).update({"resolved_at": datetime.now() - timedelta(days=31)})
        session.flush()
        assert repo.archive_terminal() == 1
        session.rollback()


class TestRiskEvents:
    """风险事件：预置处置建议 + 读取置 notified。"""

    def test_append_with_advice_and_mark_notified(self, env):
        test_env, session = env
        repo = RiskEventRepository(session)
        row = repo.append("boss_zhipin", "rate_limited")
        assert "限流" in row.advice
        unnotified = repo.list_unnotified()
        assert len(unnotified) == 1
        repo.mark_notified_batch([r.event_id for r in unnotified])
        assert repo.list_unnotified() == []
        session.rollback()


class TestCaptchaGate:
    """验证码门闸：pending 期间一切命令快速失败。"""

    def test_gate_blocks_when_pending(self, env):
        test_env, session = env
        session_factory = test_env.database.session
        open_challenge(session_factory, "boss_zhipin", "delivery")
        with pytest.raises(PlatformRateLimitedError, match="需人工验证"):
            gate_check(session_factory, "boss_zhipin", "delivery")
        # 其他平台不受影响
        gate_check(session_factory, "zhilian", "delivery")

    def test_gate_open_when_no_pending(self, env):
        test_env, session = env
        session_factory = test_env.database.session
        gate_check(session_factory, "boss_zhipin", "fetch")  # 无挑战不拦截


class TestRiskClassifier:
    """五类平台信号各归入正确异常类型。"""

    def test_banned_signal(self, env):
        test_env, session = env
        exc_cls, event = risk_detector.classify_text_signal("您的账号已被封禁")
        assert exc_cls is PlatformAuthExpiredError
        assert event == "account_banned"

    def test_restricted_signal(self, env):
        exc_cls, event = risk_detector.classify_text_signal("检测到账号异常行为")
        assert exc_cls is PlatformRateLimitedError
        assert event == "account_restricted"

    def test_rate_limited_signal(self, env):
        exc_cls, event = risk_detector.classify_text_signal("访问过于频繁，请稍后再试")
        assert exc_cls is PlatformRateLimitedError
        assert event == "rate_limited"

    def test_login_redirect_signal(self, env):
        exc_cls, event = risk_detector.classify_text_signal("任意文案", login_url_hint=True)
        assert exc_cls is PlatformAuthExpiredError
        assert event is None

    def test_normal_text_no_signal(self, env):
        assert risk_detector.classify_text_signal("欢迎回来，职位推荐") is None

    def test_parse_failure_records_event(self, env):
        test_env, session = env
        session_factory = test_env.database.session
        with pytest.raises(PlatformUnavailableError):
            risk_detector.raise_for_parse_failure("boss_zhipin", session_factory, "result_container")
        events = RiskEventRepository(session).list_unnotified()
        assert events and events[0].event_type == "interface_changed"
        session.rollback()


class TestSelectorFallback:
    """9.2 选择器多候选降级与失败环节记录。"""

    def test_first_candidate_hit(self):
        group = SelectorGroup("btn", ["[data-test='ok']", ".btn"], parse_stage="btn_missing")
        calls = []

        def attempt(selector):
            calls.append(selector)
            return object() if selector == "[data-test='ok']" else None

        report = try_locate(group, attempt)
        assert report.ok is True
        assert report.success_index == 0
        assert calls == ["[data-test='ok']"]

    def test_fallback_to_second_candidate(self):
        group = SelectorGroup("btn", ["[data-test='x']", ".btn"], parse_stage="btn_missing")

        def attempt(selector):
            return object() if selector == ".btn" else None

        report = try_locate(group, attempt)
        assert report.success_index == 1

    def test_all_failed_records_parse_stage(self):
        group = SelectorGroup("card", [".a", ".b"], parse_stage="card_missing")

        def attempt(selector):
            raise RuntimeError("元素不可用")

        report = try_locate(group, attempt)
        assert report.ok is False
        assert report.parse_stage == "card_missing"
        assert report.tried == [".a", ".b"]


class TestCredentialConversion:
    """storage_state 凭证转换：合法往返 + 非法拒绝。"""

    def test_roundtrip(self):
        state = {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}
        credential = storage_state_to_credential(state)
        assert credential_to_storage_state(credential) == state

    def test_invalid_credential_rejected(self):
        with pytest.raises(PlatformAuthExpiredError):
            credential_to_storage_state("not a json")
        with pytest.raises(PlatformAuthExpiredError):
            credential_to_storage_state('{"no_cookies": true}')


class TestSixFieldValidation:
    """必填六要素校验：缺失丢弃不影响同批次。"""

    def test_validate_positions_drops_incomplete(self, test_env):
        from app.real_platform.adapters.base import RealPlatformAdapterBase

        base = RealPlatformAdapterBase.__new__(RealPlatformAdapterBase)
        base.platform_id = "boss_zhipin"  # _validate_positions 日志依赖该属性
        raw_list = [
            {"position_id": "p1", "platform_id": "boss_zhipin", "title": "Java",
             "company": "腾讯", "city": "深圳", "publish_expire_at": datetime.now()},
            {"position_id": "p2", "platform_id": "boss_zhipin", "title": "Python",
             "company": "", "city": "深圳", "publish_expire_at": datetime.now()},  # 缺公司
            {"position_id": "", "platform_id": "boss_zhipin", "title": "Go",
             "company": "百度", "city": "北京", "publish_expire_at": datetime.now()},  # 缺标识
        ]
        valid = base._validate_positions(raw_list)
        assert len(valid) == 1
        assert valid[0].position_id == "p1"