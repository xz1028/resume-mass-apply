"""脱敏与截断：简历文本脱敏（正则遮蔽）、JD/简历截断（段落权重）、输入不足判定。

红线：出站内容最小化——请求体仅含脱敏简历文本 + 截断 JD 两类文本；
默认脱敏手机号与邮箱（占位符替换）；send_full_resume=true 时跳过遮蔽（风险由界面提示承担）。
"""

import re

from app.ai.ai_settings import AiSettings
from app.config import settings
from app.infra.logging import get_logger

logger = get_logger("privacy")

PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

PHONE_PLACEHOLDER = "[手机号已隐藏]"
EMAIL_PLACEHOLDER = "[邮箱已隐藏]"

# 段落权重：截断时优先保留的段落关键词（技能/经历优先，丢弃自我评价/证书类）
RESUME_PRIORITY_MARKS = ("技能", "工作经验", "工作经历", "项目经验", "项目经历", "教育", "职责", "技术栈")
RESUME_DEPRIORITY_MARKS = ("自我评价", "兴趣爱好", "证书", "获奖", "自我介绍", "座右铭")
JD_PRIORITY_MARKS = ("职责", "要求", "任职", "岗位描述", "工作内容", "职位描述", " Responsibilities", "Requirements")
JD_DEPRIORITY_MARKS = ("福利", "待遇", "公司介绍", "团队氛围", "办公环境", "五险", "奖金", "零食", "下午茶")


def mask_text(text: str, ai_settings: AiSettings) -> str:
    """按脱敏字段清单遮蔽：默认手机+邮箱；send_full_resume=true 跳过。"""
    if ai_settings.send_full_resume or not ai_settings.mask_enabled:
        return text
    fields = ai_settings.mask_fields
    result = text
    if "phone" in fields:
        result = PHONE_PATTERN.sub(PHONE_PLACEHOLDER, result)
    if "email" in fields:
        result = EMAIL_PATTERN.sub(EMAIL_PLACEHOLDER, result)
    return result


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[\n\r]+", text) if p.strip()]


def _truncate_by_paragraph_weight(text: str, limit: int, priority_marks: tuple, depriority_marks: tuple) -> str:
    """段落权重截断：优先段落在前（权重升序）、次要段落截尾，总量不超上限。"""
    if len(text) <= limit:
        return text
    paragraphs = _split_paragraphs(text)

    def weight(p: str) -> int:
        lowered = p.lower()
        for mark in depriority_marks:
            if mark.lower() in lowered:
                return 2
        for mark in priority_marks:
            if mark.lower() in lowered:
                return 0
        return 1

    ranked = sorted(paragraphs, key=weight)
    kept: list[str] = []
    total = 0
    for para in ranked:
        if total + len(para) + 1 > limit:
            if weight(para) == 0 and total == 0:
                kept.append(para[:limit])
            break
        kept.append(para)
        total += len(para) + 1
    return "\n".join(kept)[:limit]


def truncate_resume(text: str, ai_settings: AiSettings) -> str:
    return _truncate_by_paragraph_weight(
        text, ai_settings.resume_truncate_limit, RESUME_PRIORITY_MARKS, RESUME_DEPRIORITY_MARKS
    )


def truncate_jd(text: str, ai_settings: AiSettings) -> str:
    return _truncate_by_paragraph_weight(
        text, ai_settings.jd_truncate_limit, JD_PRIORITY_MARKS, JD_DEPRIORITY_MARKS
    )


def is_input_insufficient(masked_resume: str) -> bool:
    """脱敏截断后可用文本低于阈值（默认 200 字符）→ 输入不足降级。"""
    return len(masked_resume.strip()) < settings.ai_input_insufficient_threshold_chars


def prepare_resume_for_send(resume_text: str, ai_settings: AiSettings) -> tuple[str, bool]:
    """出站前处理链：脱敏 → 截断 → 输入不足判定。

    返回 (处理后文本, 是否输入不足)；输入不足时调用方走降级并记录日志。
    """
    masked = mask_text(resume_text, ai_settings)
    truncated = truncate_resume(masked, ai_settings)
    insufficient = is_input_insufficient(truncated)
    if insufficient:
        logger.warning(
            "ai_input_insufficient",
            available_chars=len(truncated),
            threshold=settings.ai_input_insufficient_threshold_chars,
        )
    return truncated, insufficient


def prepare_jd_for_send(jd_text: str, ai_settings: AiSettings) -> str:
    return truncate_jd(jd_text, ai_settings)