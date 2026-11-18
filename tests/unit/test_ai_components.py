"""AI 组件单元测试：脱敏/截断/评分解析/招呼语约束/失败分类/加密不回显/四态冷却（tasks 13.1）。"""

import pytest

from app.ai.ai_settings import AiSettings
from app.ai.llm.classifier import classify_status, failure_message, is_retryable
from app.ai.models import FailureKind, ProviderKind, TestStatus
from app.ai.privacy import (
    is_input_insufficient,
    mask_text,
    prepare_resume_for_send,
    truncate_jd,
    truncate_resume,
)
from app.ai.greeting.service import sanitize_greeting, template_greeting
from app.ai.matching.service import jd_hash_of, parse_score_response, resume_hash_of
from app.ai.llm.presets import PROVIDER_PRESETS, get_preset, requires_key


class F:
    phone = "13800138000"
    email = "user@example.com"


class FakeAiSettings:
    def __init__(self, mask=True, fields=None, full=False, jd_limit=2000, resume_limit=3000):
        self.mask_enabled = mask
        self.mask_fields = fields or ["phone", "email"]
        self.send_full_resume = full
        self.jd_truncate_limit = jd_limit
        self.resume_truncate_limit = resume_limit


RESUME_WITH_CONTACT = (
    "张三，手机 13800138000，邮箱 user@example.com。\n"
    "技能：Java Python Spring MySQL Docker Kubernetes 微服务架构设计与领域驱动开发\n"
    "工作经历：3 年后端开发，主导订单系统重构与支付网关建设，带教两名初级工程师\n"
    "项目经验：电商中台，日均百万级订单，负责服务拆分、缓存体系与性能优化，压测调优\n"
    "教育背景：计算机科学与技术专业，系统学习数据结构、操作系统与计算机网络\n"
    "自我评价：认真负责，抗压能力强，持续学习\n"
)


# ---------- 脱敏（tasks 4.1） ----------


def test_mask_phone_and_email_default():
    masked = mask_text(RESUME_WITH_CONTACT, FakeAiSettings())
    assert "13800138000" not in masked
    assert "user@example.com" not in masked
    assert "[手机号已隐藏]" in masked
    assert "[邮箱已隐藏]" in masked
    assert "Java" in masked  # 正文不受影响


def test_mask_disabled_when_send_full_resume():
    text = mask_text(RESUME_WITH_CONTACT, FakeAiSettings(full=True))
    assert "13800138000" in text
    assert "user@example.com" in text


def test_mask_only_phone_field():
    masked = mask_text(RESUME_WITH_CONTACT, FakeAiSettings(fields=["phone"]))
    assert "13800138000" not in masked
    assert "user@example.com" in masked  # 邮箱未脱敏


# ---------- 截断与输入不足（tasks 4.2/4.3） ----------


def test_truncate_jd_priority_sections_kept():
    jd = (
        "公司介绍：我们是一家充满活力的公司，提供零食与下午茶。\n" * 30
        + "岗位职责：负责订单系统开发。\n"
        + "任职要求：3 年 Java 经验，熟悉 MySQL。\n"
        + "福利待遇：五险一金，团队氛围好。\n" * 30
    )
    truncated = truncate_jd(jd, FakeAiSettings(jd_limit=120))
    assert len(truncated) <= 120
    assert "任职要求" in truncated  # 优先段落保留


def test_truncate_resume_keeps_skills_over_self_evaluation():
    resume = "自我评价：我很努力。\n" * 50 + "技能：Java Python SQL\n" * 5
    truncated = truncate_resume(resume, FakeAiSettings(resume_limit=60))
    assert "技能" in truncated


def test_input_insufficient_threshold():
    assert is_input_insufficient("太短") is True
    assert is_input_insufficient("字" * 250) is False


def test_prepare_resume_full_chain():
    processed, insufficient = prepare_resume_for_send(RESUME_WITH_CONTACT, FakeAiSettings())
    assert insufficient is False
    assert "13800138000" not in processed


# ---------- 评分解析（tasks 7.1） ----------


def test_parse_valid_score():
    parsed = parse_score_response('{"score": 87, "reason": "技能契合度高，经验匹配"}')
    assert parsed == (87, "技能契合度高，经验匹配")


def test_parse_code_block_wrapped():
    parsed = parse_score_response('```json\n{"score": 72, "reason": "部分匹配"}\n```')
    assert parsed is not None and parsed[0] == 72


def test_parse_extra_text_around_json():
    parsed = parse_score_response('评估结果如下：{"score": 65, "reason": "一般"} 请参考')
    assert parsed is not None and parsed[0] == 65


def test_parse_score_out_of_range_rejected():
    assert parse_score_response('{"score": 120, "reason": "x"}') is None
    assert parse_score_response('{"score": -5, "reason": "x"}') is None


def test_parse_non_numeric_score_rejected():
    assert parse_score_response('{"score": "87", "reason": "x"}') is None
    assert parse_score_response('{"score": null, "reason": "x"}') is None


def test_parse_missing_reason_rejected():
    assert parse_score_response('{"score": 87}') is None
    assert parse_score_response('{"score": 87, "reason": ""}') is None


def test_parse_garbage_rejected():
    assert parse_score_response("服务繁忙，请稍后再试") is None
    assert parse_score_response("") is None


# ---------- 招呼语约束校验（tasks 8.2） ----------


def test_sanitize_greeting_truncate_and_strip_contact():
    raw = "您好！我是 " + F.phone + "，邮箱 " + F.email + "，" + "很感兴趣" * 100
    cleaned = sanitize_greeting(raw, 100)
    assert len(cleaned) <= 100
    assert F.phone not in cleaned
    assert F.email not in cleaned


def test_sanitize_greeting_keeps_normal_text():
    text = "您好，我有 3 年 Java 经验，与贵司岗位高度匹配，期待沟通。"
    assert sanitize_greeting(text, 200) == text


def test_template_greeting_contains_title():
    from datetime import datetime

    from app.domain.models import JobPosition

    position = JobPosition(
        position_id="p1", platform_id="mock_platform", title="Java 开发",
        company="A", city="深圳", salary_min=10000, salary_max=20000,
        industry="互联网", experience_req="3-5年",
        publish_expire_at=datetime.now(), fetched_at=datetime.now(),
    )
    assert "Java 开发" in template_greeting(position)


# ---------- 失败分类映射（tasks 3.3 五类异常） ----------


def test_classify_invalid_key():
    assert classify_status(401) == FailureKind.invalid_key
    assert classify_status(403) == FailureKind.invalid_key


def test_classify_rate_limited():
    assert classify_status(429) == FailureKind.rate_limited


def test_classify_insufficient_quota():
    assert classify_status(402) == FailureKind.insufficient_quota
    assert classify_status(200, "insufficient balance") == FailureKind.insufficient_quota
    assert classify_status(200, "账户余额不足") == FailureKind.insufficient_quota


def test_classify_unreachable_5xx():
    assert classify_status(503) == FailureKind.unreachable


def test_classify_bad_format_other():
    assert classify_status(400, "bad request") == FailureKind.bad_format


def test_failure_message_ollama_hint():
    message = failure_message(FailureKind.unreachable, "ollama")
    assert "Ollama" in message
    assert "已启动" in message


def test_is_retryable_policy():
    assert is_retryable(FailureKind.timeout) is True
    assert is_retryable(FailureKind.rate_limited) is True
    assert is_retryable(FailureKind.unreachable) is True
    assert is_retryable(FailureKind.invalid_key) is False
    assert is_retryable(FailureKind.insufficient_quota) is False
    assert is_retryable(FailureKind.bad_format) is False


# ---------- 服务商预设（tasks 3.1：零内置 Key） ----------


def test_presets_no_builtin_keys():
    for provider, preset in PROVIDER_PRESETS.items():
        assert "key" not in [k for k in preset.keys() if k in ("api_key", "key")]
        assert preset["base_url"].startswith("http")


def test_requires_key_matrix():
    assert requires_key("deepseek") is True
    assert requires_key("qwen") is True
    assert requires_key("kimi") is True
    assert requires_key("zhipu") is True
    assert requires_key("openai_compat") is True
    assert requires_key("ollama") is False


def test_get_preset_fallback():
    preset = get_preset("unknown_provider")
    assert preset["base_url"].startswith("http")


# ---------- 缓存指纹（tasks 7.2 双指纹） ----------


def test_resume_hash_changes_with_content():
    assert resume_hash_of("简历A") != resume_hash_of("简历B")
    assert resume_hash_of("简历A") == resume_hash_of("简历A")


def test_jd_hash_changes_with_content():
    assert jd_hash_of("JD1") != jd_hash_of("JD2")


# ---------- 配置服务：Key 加密不回显（tasks 5.1，依赖测试环境） ----------


class TestModelConfigService:
    def test_create_and_key_not_echoed(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService

            svc = ModelConfigService(session)
            dto = svc.create_config(
                name="测试配置", provider="deepseek", base_url=None,
                model_name="deepseek-chat", api_key="sk-test-123",
            )
            assert dto["has_api_key"] is True
            assert "api_key" not in dto
            assert "sk-test-123" not in str(dto)
            configs = svc.list_configs()
            assert len(configs) == 1
            assert configs[0]["has_api_key"] is True
            assert "sk-test" not in str(configs[0])
        finally:
            session.close()

    def test_cloud_provider_requires_key(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService
            from app.api.v1.errors import AiApiKeyRequiredError

            svc = ModelConfigService(session)
            with pytest.raises(AiApiKeyRequiredError):
                svc.create_config(
                    name="无Key", provider="deepseek", base_url=None,
                    model_name="deepseek-chat", api_key=None,
                )
        finally:
            session.close()

    def test_name_conflict_rejected(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService
            from app.api.v1.errors import AiConfigNameConflictError

            svc = ModelConfigService(session)
            svc.create_config(name="唯一名", provider="deepseek", base_url=None,
                              model_name="deepseek-chat", api_key="sk-1")
            with pytest.raises(AiConfigNameConflictError):
                svc.create_config(name="唯一名", provider="deepseek", base_url=None,
                                  model_name="deepseek-chat", api_key="sk-2")
        finally:
            session.close()

    def test_activate_requires_success_test(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService
            from app.api.v1.errors import AiConfigNotTestedError

            svc = ModelConfigService(session)
            dto = svc.create_config(name="待激活", provider="ollama", base_url=None,
                                    model_name="qwen2.5:7b", api_key=None)
            with pytest.raises(AiConfigNotTestedError):
                svc.activate_config(dto["config_id"])
            # force 通道放行
            activated = svc.activate_config(dto["config_id"], force=True)
            assert activated["is_active"] is True
        finally:
            session.close()

    def test_activate_exclusive_single_active(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService

            svc = ModelConfigService(session)
            a = svc.create_config(name="A", provider="ollama", base_url=None,
                                   model_name="m1", api_key=None)
            b = svc.create_config(name="B", provider="ollama", base_url=None,
                                  model_name="m2", api_key=None)
            svc.activate_config(a["config_id"], force=True)
            svc.activate_config(b["config_id"], force=True)
            actives = [c for c in svc.list_configs() if c["is_active"]]
            assert len(actives) == 1
            assert actives[0]["name"] == "B"
        finally:
            session.close()

    def test_delete_active_rejected(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService

            svc = ModelConfigService(session)
            dto = svc.create_config(name="激活中", provider="ollama", base_url=None,
                                     model_name="m", api_key=None)
            svc.activate_config(dto["config_id"], force=True)
            with pytest.raises(Exception):
                svc.delete_config(dto["config_id"])
        finally:
            session.close()

    def test_availability_states(self, test_env):
        session = test_env.database.session()
        try:
            from app.ai.config.service import ModelConfigService

            svc = ModelConfigService(session)
            assert svc.availability()["state"] == "off"  # 无激活配置
            dto = svc.create_config(name="可用", provider="ollama", base_url=None,
                                     model_name="m", api_key=None)
            svc.activate_config(dto["config_id"], force=True)
            assert svc.availability()["state"] == "ready"
        finally:
            session.close()

    def test_cooldown_after_invalid_key_test(self, test_env):
        """invalid_key 测试结论联动冷却标记：冷却期内四态为 degraded_cooldown。"""
        session = test_env.database.session()
        try:
            from datetime import datetime

            from app.ai.config.service import ModelConfigService
            from app.ai.models import AiModelConfigRow
            from app.ai.repositories import ModelConfigRepository
            from sqlalchemy import select

            svc = ModelConfigService(session)
            dto = svc.create_config(name="冷却", provider="ollama", base_url=None,
                                    model_name="m", api_key=None)
            repo = ModelConfigRepository(session)
            row = repo.get(dto["config_id"])
            row.last_test_status = "invalid_key"
            row.is_active = True
            session.flush()
            # availability 判定要求 degraded_until 在未来
            from datetime import timedelta

            row.degraded_until = datetime.now() + timedelta(seconds=600)
            row.degraded_reason = "invalid_key"
            session.commit()
            state = svc.availability()
            assert state["state"] == "degraded_cooldown"
            assert "Key" in state["message"] or "检查" in state["message"]
        finally:
            session.close()


# ---------- KV 设置默认值（tasks 2.4 开箱即用） ----------


def test_ai_settings_defaults_without_writes(test_env):
    session = test_env.database.session()
    try:
        settings = AiSettings(session)
        assert settings.enabled is True
        assert settings.mask_enabled is True
        assert settings.mask_fields == ["phone", "email"]
        assert settings.jd_truncate_limit == 2000
        assert settings.resume_truncate_limit == 3000
        assert settings.greeting_max_len == 200
        assert settings.greeting_tone == "professional"
        assert settings.send_full_resume is False
    finally:
        session.close()


def test_ai_settings_roundtrip(test_env):
    session = test_env.database.session()
    try:
        settings = AiSettings(session)
        settings.set("ai_enabled", False)
        settings.set("ai_greeting_tone", "enthusiastic")
        assert settings.enabled is False
        assert settings.greeting_tone == "enthusiastic"
    finally:
        session.close()