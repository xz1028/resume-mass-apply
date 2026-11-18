"""AI 招呼语服务：批量生成、内容约束校验、编辑保存、投递链路最终版读取。

约束（tasks 8.1-8.4）：
- 支持开场白平台：BOSS直聘（沟通制）；mock 平台纳入以支撑演示流程
- 缓存命中直接复用（双指纹键同构）；单职位失败仅该职位回退固定模板标"模板"
- 内容校验入库前统一执行（超长截断 + 联系方式剔除）
- 编辑仅限 pending_confirm 任务（43005）；edited 独立列不覆盖 AI 原版
- 最终版合成：编辑版 > AI 生成版 > None（None 由适配器固定模板兜底）
"""

import re

from sqlalchemy.orm import Session

from app.ai.ai_settings import AiSettings
from app.ai.config.service import ModelConfigService
from app.ai.jd.fetcher import fetch_jd
from app.ai.llm.client import LlmCallError, get_llm_client
from app.ai.matching.service import jd_hash_of, resume_hash_of
from app.ai.models import AiGreetingRow, CallKind, FailureKind, GreetingSource
from app.ai.privacy import EMAIL_PATTERN, PHONE_PATTERN, prepare_jd_for_send, prepare_resume_for_send
from app.ai.prompts import build_greeting_messages
from app.ai.repositories import AiGreetingRepository, ModelConfigRepository
from app.api.v1.errors import GreetingEditConflictError, GreetingTooLongError, NotFoundError
from app.domain.models import TaskStatus
from app.domain.models import JobPosition
from app.infra.logging import get_logger
from app.repositories.repos import TaskRepository

logger = get_logger("greeting_service")

GREETING_PLATFORMS = {"boss_zhipin", "mock_platform"}

DEFAULT_TEMPLATE = (
    "您好，我对贵公司「{title}」职位很感兴趣，"
    "具备相应技能与经验，期待进一步沟通，我的简历已随消息附上，感谢查阅！"
)

TASK_STATUS_EDITABLE = {TaskStatus.pending_confirm}


def sanitize_greeting(text: str, max_len: int) -> str:
    """内容约束校验：超长截断 + 剔除联系方式；入库前统一执行。"""
    cleaned = PHONE_PATTERN.sub("", text)
    cleaned = EMAIL_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


def template_greeting(position: JobPosition) -> str:
    return DEFAULT_TEMPLATE.format(title=position.title)


class GreetingService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------- 降级判定 ----------

    def _degrade_or_none(self) -> tuple[str, str] | None:
        ai_settings = AiSettings(self._session)
        if not ai_settings.enabled:
            return "ai_disabled", "AI 功能未启用，使用固定模板招呼语"
        availability = ModelConfigService(self._session).availability()
        if availability["state"] == "off":
            return "no_active_config", "未配置模型服务，使用固定模板招呼语"
        if availability["state"] == "degraded_cooldown":
            return "config_cooldown", availability["message"]
        return None

    # ---------- 单职位生成 ----------

    async def generate_one(
        self,
        user_id: str,
        resume_text: str,
        position: JobPosition,
        delivery_task_id: str,
    ) -> dict:
        """单职位招呼语生成链：缓存命中→脱敏截断→Prompt→LLM→约束校验→落库。

        返回 {status: ok|template, text, source}。
        """
        repo = AiGreetingRepository(self._session)
        ai_settings = AiSettings(self._session)

        degrade = self._degrade_or_none()
        if degrade is not None:
            logger.info("greeting_degraded", position_id=position.position_id, reason=degrade[0])
            return {"status": "template", "text": template_greeting(position), "source": GreetingSource.template.value}

        r_hash = resume_hash_of(resume_text)
        cached = repo.find(user_id, r_hash, position.position_id, "")
        if cached is not None and cached.text:
            from app.infra.metrics import inc_ai_cache_hit

            inc_ai_cache_hit("greeting")
            return {"status": "ok", "text": cached.text, "source": GreetingSource.ai.value}

        jd_text, _ = await fetch_jd(self._session, position, ai_settings)
        masked_resume, insufficient = prepare_resume_for_send(resume_text, ai_settings)
        if insufficient:
            return {"status": "template", "text": template_greeting(position), "source": GreetingSource.template.value}
        jd_truncated = prepare_jd_for_send(jd_text, ai_settings)

        active = ModelConfigRepository(self._session).get_active()
        if active is None:
            return {"status": "template", "text": template_greeting(position), "source": GreetingSource.template.value}
        api_key = ModelConfigService._decrypt_key(active) or None

        client = get_llm_client()
        messages = build_greeting_messages(
            jd_truncated, masked_resume, ai_settings.greeting_tone, ai_settings.greeting_max_len
        )
        try:
            content = await client.chat(
                base_url=active.base_url,
                model_name=active.model_name,
                api_key=api_key,
                messages=messages,
                call_kind=CallKind.greeting,
                provider=active.provider,
            )
        except LlmCallError as exc:
            if exc.kind in (FailureKind.invalid_key, FailureKind.insufficient_quota):
                ModelConfigService(self._session).mark_hard_degrade(exc.kind)
            logger.warning(
                "greeting_llm_failed",
                position_id=position.position_id,
                kind=exc.kind.value,
                message="该职位回退固定模板招呼语",
            )
            return {"status": "template", "text": template_greeting(position), "source": GreetingSource.template.value}

        text = sanitize_greeting(content, ai_settings.greeting_max_len)
        if not text.strip():
            return {"status": "template", "text": template_greeting(position), "source": GreetingSource.template.value}
        repo.save(
            user_id=user_id,
            resume_hash=r_hash,
            position_id=position.position_id,
            jd_hash="",
            delivery_task_id=delivery_task_id,
            text=text,
            source=GreetingSource.ai.value,
        )
        self._session.commit()
        return {"status": "ok", "text": text, "source": GreetingSource.ai.value}

    # ---------- 查询（渐进） ----------

    def list_for_task(self, delivery_task_id: str) -> list[dict]:
        rows = AiGreetingRepository(self._session).find_by_task(delivery_task_id)
        items = []
        for row in rows:
            source = (
                GreetingSource.edited.value if row.edited_text else row.source
            )
            text = row.edited_text or row.text
            items.append(
                {
                    "position_id": row.position_id,
                    "text": text,
                    "source": source,
                    "generating": False,
                }
            )
        return items

    # ---------- 编辑保存 ----------

    def edit(self, delivery_task_id: str, position_id: str, text: str) -> dict:
        task = TaskRepository(self._session).get(delivery_task_id)
        if task is None or task.status not in TASK_STATUS_EDITABLE:
            raise GreetingEditConflictError("任务已确认或已终态，招呼语不可再编辑")
        ai_settings = AiSettings(self._session)
        text = (text or "").strip()
        if not text:
            raise GreetingTooLongError("招呼语不能为空")
        if len(text) > ai_settings.greeting_max_len:
            raise GreetingTooLongError(f"招呼语超过长度上限（{ai_settings.greeting_max_len} 字）")
        cleaned = sanitize_greeting(text, ai_settings.greeting_max_len)
        repo = AiGreetingRepository(self._session)
        row = repo.find_by_task_and_position(delivery_task_id, position_id)
        if row is None:
            row = repo.save(
                user_id=task.user_id,
                resume_hash="",
                position_id=position_id,
                jd_hash="",
                delivery_task_id=delivery_task_id,
                text=cleaned,
                source=GreetingSource.template.value,
            )
        repo.set_edited(delivery_task_id, position_id, cleaned)
        self._session.commit()
        return {"position_id": position_id, "text": cleaned, "source": GreetingSource.edited.value}

    # ---------- 投递链路最终版读取（同步毫秒级） ----------

    def final_greeting(self, delivery_task_id: str, position_id: str) -> str | None:
        """最终版合成：编辑版 > AI 生成版 > None（None→适配器固定模板兜底）。

        读取异常传 None：AI 组件异常不改变投递成功/失败判定。
        """
        try:
            rows = AiGreetingRepository(self._session).find_by_task(delivery_task_id)
            for row in rows:
                if row.position_id == position_id:
                    return row.edited_text or (row.text if row.text else None)
            return None
        except Exception:  # noqa: BLE001
            logger.exception("final_greeting_read_failed", position_id=position_id)
            return None