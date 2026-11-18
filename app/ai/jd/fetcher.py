"""JD 文本获取服务：列读取 → FETCH_JD 命令（真实平台）→ 降级拼接。

规则：AI 未启用时不发起任何抓取（开箱即用零行为）；
mock 平台职位无详情页，直接结构化字段拼接模拟 JD；
抓取成功落库 jd_text/jd_fetched_at（每职位仅一次）；
降级拼接 JD 按实际使用文本取指纹（发送什么就缓存什么）。
"""

import asyncio
from datetime import datetime

from app.ai.ai_settings import AiSettings
from app.domain.models import JobPosition
from app.infra.logging import get_logger
from app.repositories.repos import PositionRepository
from sqlalchemy.orm import Session

logger = get_logger("jd_fetcher")

MOCK_PLATFORM_ID = "mock_platform"


def build_fallback_jd(position: JobPosition) -> str:
    """降级拼接 JD：结构化字段合成（真实平台抓取失败/mock 职位共用）。"""
    parts = [
        f"职位：{position.title}",
        f"公司：{position.company}",
        f"城市：{position.city}",
    ]
    if position.salary_min is not None or position.salary_max is not None:
        low = position.salary_min // 1000 if position.salary_min else 0
        high = position.salary_max // 1000 if position.salary_max else 0
        if low and high:
            parts.append(f"薪资：{low}-{high}K")
        elif high:
            parts.append(f"薪资：{high}K 以下")
        elif low:
            parts.append(f"薪资：{low}K 以上")
    if position.industry:
        parts.append(f"行业：{position.industry}")
    if position.experience_req:
        parts.append(f"经验要求：{position.experience_req}")
    return "\n".join(parts)


def build_mock_jd(position: JobPosition) -> str:
    """mock 平台模拟 JD：在降级拼接基础上补充职责描述文本。"""
    base = build_fallback_jd(position)
    duty = (
        f"岗位职责：负责{position.title}相关工作，参与需求分析与方案设计，"
        "配合团队完成项目目标，持续优化工作流程与产出质量。"
        "任职要求：具备岗位所需的专业技能与沟通协作能力，有相关经验者优先。"
    )
    return f"{base}\n{duty}"


async def fetch_jd(session: Session, position: JobPosition, ai_settings: AiSettings) -> tuple[str, bool]:
    """获取该职位 JD 文本。返回 (jd_text, 是否降级拼接)。

    优先读取 jd_text 列 → mock 平台直接拼接 → 真实平台发 FETCH_JD 命令 → 失败降级拼接。
    """
    if not ai_settings.enabled:
        return build_fallback_jd(position), True

    if position.jd_text and position.jd_text.strip():
        return position.jd_text, False

    if position.platform_id == MOCK_PLATFORM_ID:
        mock_jd = build_mock_jd(position)
        _persist_jd(session, position, mock_jd)
        return mock_jd, False

    fetched = await _fetch_jd_via_browser(position)
    if fetched:
        _persist_jd(session, position, fetched)
        return fetched, False

    logger.info("jd_fallback_composed", position_id=position.position_id, platform_id=position.platform_id)
    return build_fallback_jd(position), True


async def _fetch_jd_via_browser(position: JobPosition) -> str | None:
    """经既有平台专属 worker 命令队列发起 FETCH_JD；异常返回 None（降级）。"""
    from app.real_platform.browser.session_manager import get_session_manager
    from app.real_platform.browser.worker import BrowserCommand, OpType

    manager = get_session_manager()
    worker = manager.worker_for(position.platform_id)
    from app.platforms.registry import get_registry

    registry = get_registry()
    adapter = registry.get(position.platform_id)
    if adapter is None:
        return None
    worker.bind_executor(adapter._page_executor)
    worker.start()
    command = BrowserCommand(op_type=OpType.FETCH_JD, payload={"position": position})
    try:
        result = await asyncio.to_thread(worker.submit, command)
        return result if isinstance(result, str) and result.strip() else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("jd_fetch_failed", position_id=position.position_id, reason=str(exc)[:120])
        return None


def _persist_jd(session: Session, position: JobPosition, jd_text: str) -> None:
    """抓取成功落库（每职位仅抓取一次）；失败不落库等待下次重试。"""
    try:
        repo = PositionRepository(session)
        from app.repositories.orm import JobPositionRow

        row = session.query(JobPositionRow).filter(
            JobPositionRow.platform_id == position.platform_id,
            JobPositionRow.position_id == position.position_id,
        ).first()
        if row is not None and not row.jd_text:
            row.jd_text = jd_text
            row.jd_fetched_at = datetime.now()
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jd_persist_failed", position_id=position.position_id, reason=str(exc)[:120])
        session.rollback()