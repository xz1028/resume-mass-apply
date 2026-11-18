"""AI 匹配服务：降级判定链、评分解析校验、双指纹缓存、逐职位处理链。

D1 红线：AI 不进推荐主链路（GET /recommendations 的 match_score 语义零改动）；
降级判定链逐级短路：AI 开关关→无激活配置→配置级冷却中→缓存命中→输入不足；
单职位失败仅标记 fallback 不中断批任务。
"""

import asyncio
import hashlib
import json
import re

from sqlalchemy.orm import Session

from app.ai.ai_settings import AiSettings
from app.ai.config.service import ModelConfigService
from app.ai.jd.fetcher import fetch_jd
from app.ai.llm.client import LlmCallError, get_llm_client
from app.ai.llm.classifier import is_retryable
from app.ai.models import AiMatchResultRow, CallKind, FailureKind
from app.ai.privacy import prepare_jd_for_send, prepare_resume_for_send
from app.ai.prompts import build_match_messages
from app.ai.repositories import AiMatchCacheRepository, AiCallLogRepository
from app.config import settings
from app.domain.models import JobPosition
from app.infra.logging import get_logger

logger = get_logger("ai_matching")

SCORE_JSON_PATTERN = re.compile(r"\{[^{}]*\"score\"[^{}]*\}", re.DOTALL)
REASON_MAX_CHARS = 500


def resume_hash_of(resume_text: str) -> str:
    """简历指纹：sha256(默认简历解密全文)，与既有 matching_service 缓存键同源同算法。"""
    return hashlib.sha256(resume_text.encode("utf-8")).hexdigest()


def jd_hash_of(jd_text: str) -> str:
    """JD 指纹：sha256(实际使用 JD 文本)——发送什么就缓存什么。"""
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()


def parse_score_response(content: str) -> tuple[int, str] | None:
    """容错提取 JSON 评分对象：score 0-100 整数 + reason ≤500 字；异常返回 None（bad_format）。"""
    if not content:
        return None
    candidates: list[str] = []
    stripped = content.strip()
    if stripped.startswith("```"):
        inner = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", stripped)
        candidates.append(inner.strip())
    candidates.append(stripped)
    match = SCORE_JSON_PATTERN.search(stripped)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        score = data.get("score")
        reason = data.get("reason")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        if not (0 <= int(score) <= 100):
            continue
        reason_text = str(reason or "").strip()
        if not reason_text:
            continue
        return int(score), reason_text[:REASON_MAX_CHARS]
    return None


class AiMatchingService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------- 降级判定链 ----------

    def _degrade_or_none(self) -> tuple[str, str] | None:
        """逐级短路：返回 (降级原因, 用户提示) 或 None（可继续）。"""
        ai_settings = AiSettings(self._session)
        if not ai_settings.enabled:
            return "ai_disabled", "AI 功能未启用，使用规则评分"
        availability = ModelConfigService(self._session).availability()
        state = availability["state"]
        if state == "off":
            return "no_active_config", "未配置模型服务，使用规则评分"
        if state == "degraded_cooldown":
            return "config_cooldown", availability["message"]
        return None

    # ---------- 单职位处理 ----------

    async def score_one(
        self,
        user_id: str,
        resume_text: str,
        position: JobPosition,
    ) -> dict:
        """单职位评分链：缓存命中→JD 获取→脱敏截断→Prompt→LLM→解析校验→落缓存。

        返回 {status: ok|fallback, ai_score, reason, degrade_message}。
        """
        ai_settings = AiSettings(self._session)
        degrade = self._degrade_or_none()
        if degrade is not None:
            return {"status": "fallback", "ai_score": None, "reason": "", "degrade_message": degrade[1]}

        r_hash = resume_hash_of(resume_text)
        cache = AiMatchCacheRepository(self._session)
        jd_text, _is_fallback = await fetch_jd(self._session, position, ai_settings)
        j_hash = jd_hash_of(jd_text)
        cached = cache.find(user_id, r_hash, position.position_id, j_hash)
        if cached is not None:
            from app.infra.metrics import inc_ai_cache_hit

            inc_ai_cache_hit("match")
            return {"status": "ok", "ai_score": cached.score, "reason": cached.reason, "degrade_message": ""}

        masked_resume, insufficient = prepare_resume_for_send(resume_text, ai_settings)
        if insufficient:
            return {
                "status": "fallback",
                "ai_score": None,
                "reason": "",
                "degrade_message": "简历可用内容过少，AI 匹配暂不可用，已使用规则评分",
            }
        jd_truncated = prepare_jd_for_send(jd_text, ai_settings)

        config_service = ModelConfigService(self._session)
        from app.ai.repositories import ModelConfigRepository

        active = ModelConfigRepository(self._session).get_active()
        if active is None:
            return {"status": "fallback", "ai_score": None, "reason": "", "degrade_message": "未配置模型服务，使用规则评分"}
        api_key = ModelConfigService._decrypt_key(active) or None

        client = get_llm_client()
        messages = build_match_messages(jd_truncated, masked_resume)
        try:
            content = await client.chat(
                base_url=active.base_url,
                model_name=active.model_name,
                api_key=api_key,
                messages=messages,
                call_kind=CallKind.match,
                provider=active.provider,
            )
        except LlmCallError as exc:
            self._record_call(active.provider, CallKind.match, exc)
            if exc.kind in (FailureKind.invalid_key, FailureKind.insufficient_quota):
                config_service.mark_hard_degrade(exc.kind)
            else:
                config_service.mark_transient_degrade(exc.kind.value)
            return {"status": "fallback", "ai_score": None, "reason": "", "degrade_message": exc.message}
        self._record_call(active.provider, CallKind.match, None)

        parsed = parse_score_response(content)
        if parsed is None:
            logger.warning("ai_score_parse_failed", position_id=position.position_id)
            return {
                "status": "fallback",
                "ai_score": None,
                "reason": "",
                "degrade_message": "模型返回格式异常，已使用规则评分",
            }
        score, reason = parsed
        cache.save(user_id, r_hash, position.position_id, j_hash, score, reason)
        self._session.commit()
        return {"status": "ok", "ai_score": score, "reason": reason, "degrade_message": ""}

    # ---------- 批处理（编排器调用） ----------

    async def score_batch(
        self,
        user_id: str,
        resume_text: str,
        positions: list[JobPosition],
        on_progress=None,
    ) -> dict:
        """逐职位串行处理（Semaphore 并发由编排器控制；此处逐职位独立提交）。"""
        results: dict[str, dict] = {}
        semaphore = asyncio.Semaphore(settings.ai_concurrency)

        async def _one(position: JobPosition) -> None:
            async with semaphore:
                result = await self.score_one(user_id, resume_text, position)
                results[position.position_id] = result
                if on_progress is not None:
                    on_progress(position.position_id, result)

        await asyncio.gather(*[_one(p) for p in positions], return_exceptions=False)
        return results

    def _record_call(self, provider: str, call_kind: CallKind, exc: LlmCallError | None) -> None:
        from app.infra.metrics import inc_ai_call

        try:
            AiCallLogRepository(self._session).append(
                provider=provider,
                call_type=call_kind.value,
                result="success" if exc is None else "failed_degraded",
                failure_kind=exc.kind.value if exc is not None else "",
                duration_ms=0,
                attempted=1,
            )
            self._session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("ai_call_log_failed")
            self._session.rollback()
        inc_ai_call(
            provider=provider,
            call_type=call_kind.value,
            result="success" if exc is None else "failed_degraded",
        )