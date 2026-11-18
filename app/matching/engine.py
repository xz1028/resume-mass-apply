"""匹配引擎：MatchingEngine 契约（design 8.2）与默认多因子加权评分实现。

因子与默认权重：技能词命中 0.5、经验年限区间 0.2、城市契合 0.15、薪资期望匹配 0.15。
评分恒在 [0, 100] 区间；单职位计算毫秒级（远低于 2 秒约束）。
"""

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.models import JobIntention
from app.parsers.resume_parser import DefaultResumeParser, ResumeMatchProfile, ResumeRawText
from app.platforms.spi import PositionDTO


@dataclass
class MatchScore:
    value: int
    factors: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class MatchingEngine(Protocol):
    def build_resume_profile(self, text: ResumeRawText) -> ResumeMatchProfile: ...

    def compute_score(self, resume: ResumeMatchProfile, position: PositionDTO) -> MatchScore: ...


_EXP_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*年")
_EXP_PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*年以上")
_EXP_BELOW = re.compile(r"(\d+(?:\.\d+)?)\s*年以下")


def parse_experience_requirement(req: str) -> tuple[float | None, float | None]:
    """解析职位经验要求为 [min, max] 区间；None 表示不限/无法解析。"""
    if not req:
        return None, None
    m = _EXP_RANGE.search(req)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _EXP_PLUS.search(req)
    if m:
        return float(m.group(1)), None
    m = _EXP_BELOW.search(req)
    if m:
        return 0.0, float(m.group(1))
    return None, None


class WeightedFactorEngine:
    """实现 MatchingEngine 契约（无需显式继承），权重可配置。"""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        intention: JobIntention | None = None,
    ) -> None:
        self._weights = weights or {
            "skill": 0.5,
            "experience": 0.2,
            "city": 0.15,
            "salary": 0.15,
        }
        self._intention = intention or JobIntention()
        self._parser = DefaultResumeParser()

    def build_resume_profile(self, text: ResumeRawText) -> ResumeMatchProfile:
        return self._parser.build_profile(text)

    def compute_score(self, resume: ResumeMatchProfile, position: PositionDTO) -> MatchScore:
        skill = self._skill_factor(resume, position)
        experience = self._experience_factor(resume, position)
        city = self._city_factor(position)
        salary = self._salary_factor(position)
        raw = (
            self._weights["skill"] * skill
            + self._weights["experience"] * experience
            + self._weights["city"] * city
            + self._weights["salary"] * salary
        )
        value = max(0, min(100, round(raw * 100)))
        return MatchScore(
            value=value,
            factors={
                "skill": round(skill, 4),
                "experience": round(experience, 4),
                "city": round(city, 4),
                "salary": round(salary, 4),
            },
        )

    @staticmethod
    def _skill_factor(resume: ResumeMatchProfile, position: PositionDTO) -> float:
        job_text = " ".join([position.title, position.experience_req, position.industry]).lower()
        if not resume.skills:
            return 0.0
        hits = sum(1 for s in resume.skills if s in job_text)
        return hits / len(resume.skills)

    @staticmethod
    def _experience_factor(resume: ResumeMatchProfile, position: PositionDTO) -> float:
        years = resume.years_of_experience
        if years is None:
            return 0.3
        req_min, req_max = parse_experience_requirement(position.experience_req)
        if req_min is None and req_max is None:
            return 0.5
        if req_max is None:
            return 1.0 if years >= (req_min or 0) else 0.8 * years / max(req_min, 1e-6)
        if req_min is None:
            req_min = 0.0
        if req_min <= years <= req_max:
            return 1.0
        if years < req_min:
            return 0.8 * years / max(req_min, 1e-6)
        return 0.8 * req_max / max(years, 1e-6)

    def _city_factor(self, position: PositionDTO) -> float:
        expected = self._intention.city
        if not expected:
            return 0.5
        return 1.0 if position.city == expected else 0.0

    def _salary_factor(self, position: PositionDTO) -> float:
        smin, smax = self._intention.salary_min, self._intention.salary_max
        pmin, pmax = position.salary_min, position.salary_max
        if smin is None and smax is None:
            return 0.5
        if pmin is None and pmax is None:
            return 0.5
        overlap_low = max(smin or 0, pmin or 0)
        overlap_high = min(smax or float("inf"), pmax or float("inf"))
        return 1.0 if overlap_low <= overlap_high else 0.0