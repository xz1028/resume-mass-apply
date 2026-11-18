"""生效评分查询：圈选与展示共用的"当前生效评分"（AI 评分优先，降级/无 AI 时等于规则分）。

设计（tasks 10.4）：effective_score 叠加字段不改 match_score 语义与推荐排序行为；
AI 未启用/无缓存时 effective_score == match_score（与既有圈选结果完全一致）。
"""

from sqlalchemy.orm import Session

from app.infra.logging import get_logger

logger = get_logger("effective_score")


def overlay_effective_scores(session: Session, user_id: str, items: list[dict]) -> list[dict]:
    """就地叠加 effective_score 字段；返回同一列表（调用方零适配）。"""
    for item in items:
        item.setdefault("effective_score", item.get("match_score") or 0)
    if not items:
        return items
    try:
        from app.ai.ai_settings import AiSettings
        from app.ai.matching.service import resume_hash_of

        if not AiSettings(session).enabled:
            return items

        from app.ai.tasks import _get_resume_text

        resume_text, owner = _get_resume_text(session)
        if owner != user_id or not resume_text:
            return items
        r_hash = resume_hash_of(resume_text)

        from app.ai.tasks import _find_any_score

        for item in items:
            position = item.get("position")
            if position is None:
                continue
            cached = _find_any_score(session, user_id, r_hash, position.position_id)
            if cached is not None:
                item["effective_score"] = cached.score
    except Exception:  # noqa: BLE001
        logger.exception("effective_score_overlay_failed")
    return items