"""模型配置管理服务：CRUD、Key 加密、单激活切换、连通性测试编排、四态冷却门面。

红线：Key 提交后立即加密落库（明文仅存在于请求入参与解密调用瞬间）；
查询接口永不返回 Key 字段（DTO 仅 has_api_key: bool）；
删除仅允许未激活配置；激活前置最近测试 success（force 通道除外）。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.ai.ai_settings import AiSettings
from app.ai.llm.client import get_llm_client
from app.ai.llm.presets import get_preset, requires_key
from app.ai.models import AiModelConfigRow, FailureKind, ProviderKind, TestStatus
from app.ai.repositories import ModelConfigRepository
from app.api.v1.errors import (
    AiApiKeyRequiredError,
    AiConfigNameConflictError,
    AiConfigNotTestedError,
    AiModelConfigNotFoundError,
)
from app.config import settings
from app.infra.audit import AuditAction, record_audit
from app.infra.crypto import get_crypto
from app.infra.logging import get_logger

logger = get_logger("model_config_service")


class ModelConfigService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------- DTO（Key 永不回显） ----------

    @staticmethod
    def _to_dto(row: AiModelConfigRow) -> dict:
        return {
            "config_id": row.config_id,
            "name": row.name,
            "provider": row.provider,
            "base_url": row.base_url,
            "model_name": row.model_name,
            "has_api_key": row.api_key_cipher is not None,
            "is_active": row.is_active,
            "last_test_status": row.last_test_status or "none",
            "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
            "last_test_message": row.last_test_message or "",
            "degraded": bool(row.degraded_until and row.degraded_until > datetime.now()),
            "degraded_reason": row.degraded_reason or "",
            "created_at": row.created_at.isoformat(),
        }

    def list_configs(self) -> list[dict]:
        return [self._to_dto(r) for r in ModelConfigRepository(self._session).list_all()]

    def get_config(self, config_id: str) -> dict:
        row = ModelConfigRepository(self._session).get(config_id)
        if row is None:
            raise AiModelConfigNotFoundError()
        return self._to_dto(row)

    # ---------- CRUD ----------

    def create_config(
        self,
        name: str,
        provider: str,
        base_url: str | None,
        model_name: str,
        api_key: str | None,
    ) -> dict:
        repo = ModelConfigRepository(self._session)
        if repo.get_by_name(name) is not None:
            raise AiConfigNameConflictError()
        preset = get_preset(provider)
        if provider == ProviderKind.openai_compat.value and not (base_url or "").strip():
            from app.api.v1.errors import InvalidParamError

            raise InvalidParamError("自定义兼容接口必须填写接口地址")
        if provider == ProviderKind.openai_compat.value:
            effective_base_url = (base_url or "").strip().rstrip("/")
        else:
            effective_base_url = (base_url or "").strip().rstrip("/") or preset["base_url"]
        if requires_key(provider) and not (api_key or "").strip():
            raise AiApiKeyRequiredError()
        cipher = None
        if (api_key or "").strip():
            cipher = get_crypto().encrypt(api_key.strip().encode("utf-8"))
        row = repo.add(
            AiModelConfigRow(
                name=name.strip(),
                provider=provider,
                base_url=effective_base_url,
                model_name=(model_name or "").strip() or preset["default_model"],
                api_key_cipher=cipher,
                is_active=False,
            )
        )
        self._session.commit()
        logger.info("ai_config_created", config_id=row.config_id, provider=provider, name=row.name)
        return self._to_dto(row)

    def update_config(
        self,
        config_id: str,
        name: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        repo = ModelConfigRepository(self._session)
        row = repo.get(config_id)
        if row is None:
            raise AiModelConfigNotFoundError()
        key_replaced = False
        if name is not None and name.strip() and name.strip() != row.name:
            if repo.get_by_name(name.strip()) is not None:
                raise AiConfigNameConflictError()
            row.name = name.strip()
        if base_url is not None and base_url.strip():
            row.base_url = base_url.strip().rstrip("/")
        if model_name is not None and model_name.strip():
            row.model_name = model_name.strip()
        if api_key is not None and api_key.strip():
            row.api_key_cipher = get_crypto().encrypt(api_key.strip().encode("utf-8"))
            key_replaced = True
        self._session.flush()
        if key_replaced:
            record_audit(
                self._session,
                AuditAction.AI_KEY_UPDATED,
                f"更新模型配置 {row.name} 的 API Key",
            )
        self._session.commit()
        return self._to_dto(row)

    def delete_config(self, config_id: str) -> None:
        repo = ModelConfigRepository(self._session)
        row = repo.get(config_id)
        if row is None:
            raise AiModelConfigNotFoundError()
        if row.is_active:
            raise AiConfigNameConflictError("激活中的配置不可删除，请先激活其他配置或停用")
        repo.delete(config_id)
        self._session.commit()
        logger.info("ai_config_deleted", config_id=config_id)

    # ---------- 激活 ----------

    def activate_config(self, config_id: str, force: bool = False) -> dict:
        repo = ModelConfigRepository(self._session)
        row = repo.get(config_id)
        if row is None:
            raise AiModelConfigNotFoundError()
        if requires_key(row.provider) and row.api_key_cipher is None:
            raise AiApiKeyRequiredError()
        if row.last_test_status != TestStatus.success.value and not force:
            raise AiConfigNotTestedError()
        previous = repo.get_active()
        repo.activate_exclusive(config_id)
        record_audit(
            self._session,
            AuditAction.AI_PROVIDER_SWITCHED,
            f"激活模型配置 {row.name}（provider={row.provider}）"
            + (f"，替换原配置 {previous.name}" if previous else ""),
        )
        self._session.commit()
        logger.info("ai_config_activated", config_id=config_id, name=row.name)
        return self._to_dto(repo.get(config_id))

    # ---------- 连通性测试 ----------

    async def test_config(self, config_id: str, draft_key: str | None = None) -> dict:
        """测试编排：草稿 Key 不落库；invalid_key/insufficient_quota 联动冷却标记。"""
        repo = ModelConfigRepository(self._session)
        row = repo.get(config_id)
        if row is None:
            raise AiModelConfigNotFoundError()
        api_key = (draft_key or "").strip() or self._decrypt_key(row)
        client = get_llm_client()
        result = await client.test_connectivity(
            base_url=row.base_url,
            model_name=row.model_name,
            api_key=api_key or None,
            provider=row.provider,
        )
        status = result.get("status", "unreachable")
        repo.update_fields(
            config_id,
            last_test_status=status,
            last_test_at=datetime.now(),
            last_test_message=result.get("message", ""),
        )
        if status in (TestStatus.invalid_key.value, TestStatus.insufficient_quota.value) and row.is_active:
            repo.update_fields(
                config_id,
                degraded_until=datetime.now() + timedelta(seconds=settings.ai_config_cooldown_seconds),
                degraded_reason=status,
            )
        self._session.commit()
        return {
            "config_id": config_id,
            "status": status,
            "message": result.get("message", ""),
            "duration_ms": result.get("duration_ms", 0),
        }

    # ---------- 四态可用性门面 ----------

    def availability(self) -> dict:
        """四态：off / ready / degraded_cooldown / degraded_transient。"""
        ai_settings = AiSettings(self._session)
        if not ai_settings.enabled:
            return {"state": "off", "message": "AI 功能未启用", "active_config": None}
        repo = ModelConfigRepository(self._session)
        active = repo.get_active()
        if active is None:
            return {"state": "off", "message": "未配置或未激活模型服务，使用规则评分", "active_config": None}
        if active.degraded_until and active.degraded_until > datetime.now():
            reason = active.degraded_reason or "unknown"
            if reason in (FailureKind.invalid_key.value, FailureKind.insufficient_quota.value):
                message = (
                    "API Key 无效，请检查后重试"
                    if reason == FailureKind.invalid_key.value
                    else "模型服务余额不足，请充值后重试"
                )
                return {
                    "state": "degraded_cooldown",
                    "message": f"{message}（冷却中，已自动回退规则评分）",
                    "active_config": active.name,
                }
        return {"state": "ready", "message": "AI 功能可用", "active_config": active.name}

    def mark_transient_degrade(self, reason: str) -> None:
        """瞬态降级（限流/超时）：仅记录日志与指标，不进冷却。"""
        repo = ModelConfigRepository(self._session)
        active = repo.get_active()
        if active is not None:
            logger.warning(
                "ai_transient_degrade",
                config_id=active.config_id,
                reason=reason,
                message="AI 暂不可用，已使用规则匹配与固定模板招呼语",
            )

    def mark_hard_degrade(self, kind: FailureKind) -> None:
        """硬降级（Key 无效/余额不足）：进入 10 分钟冷却。"""
        repo = ModelConfigRepository(self._session)
        active = repo.get_active()
        if active is not None:
            repo.update_fields(
                active.config_id,
                degraded_until=datetime.now() + timedelta(seconds=settings.ai_config_cooldown_seconds),
                degraded_reason=kind.value,
            )
            self._session.commit()
            logger.warning(
                "ai_config_degraded",
                config_id=active.config_id,
                kind=kind.value,
                cooldown_seconds=settings.ai_config_cooldown_seconds,
            )

    @staticmethod
    def _decrypt_key(row: AiModelConfigRow) -> str:
        if row.api_key_cipher is None:
            return ""
        return get_crypto().decrypt(row.api_key_cipher).decode("utf-8")