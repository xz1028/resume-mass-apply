"""匹配引擎单元测试：各因子权重、评分区间、经验区间解析。"""

from app.domain.models import JobIntention
from app.matching.engine import WeightedFactorEngine, parse_experience_requirement
from app.parsers.resume_parser import ResumeMatchProfile, ResumeRawText
from app.platforms.spi import PositionDTO


def _position(**overrides) -> PositionDTO:
    base = dict(
        position_id="p1",
        platform_id="mock_platform",
        title="Java 开发工程师（3-5年）",
        company="某互联网公司",
        city="深圳",
        salary_min=20000,
        salary_max=35000,
        industry="互联网",
        experience_req="3-5年",
    )
    base.update(overrides)
    return PositionDTO(**base)


def test_parse_experience_requirement() -> None:
    assert parse_experience_requirement("3-5年") == (3.0, 5.0)
    assert parse_experience_requirement("3年以上") == (3.0, None)
    assert parse_experience_requirement("5年以下") == (0.0, 5.0)
    assert parse_experience_requirement("经验不限") == (None, None)
    assert parse_experience_requirement("") == (None, None)


def test_java_resume_scores_higher_than_sales() -> None:
    """spec 5.3.1.1.a：Java 简历对 Java 职位的评分显著高于销售经理职位。"""
    engine = WeightedFactorEngine(intention=JobIntention(city="深圳", salary_min=15000))
    resume = ResumeMatchProfile(raw_text="Java 后端 3 年经验", skills={"java"}, years_of_experience=3.0)
    java_score = engine.compute_score(resume, _position())
    sales_score = engine.compute_score(
        resume,
        _position(
            position_id="p2",
            title="销售经理",
            company="某销售公司",
            city="上海",
            salary_min=8000,
            salary_max=12000,
            industry="销售",
            experience_req="1-3年",
        ),
    )
    assert java_score.value > sales_score.value
    assert java_score.value >= 60
    assert sales_score.value < 30


def test_score_always_in_range() -> None:
    engine = WeightedFactorEngine()
    empty_resume = ResumeMatchProfile(raw_text="", skills=set(), years_of_experience=None)
    assert 0 <= engine.compute_score(empty_resume, _position()).value <= 100
    strong_resume = ResumeMatchProfile(
        raw_text="x", skills={"java", "python", "sql"}, years_of_experience=4.0
    )
    assert 0 <= engine.compute_score(strong_resume, _position()).value <= 100


def test_experience_factor_boundaries() -> None:
    resume = ResumeMatchProfile(raw_text="x", skills=set(), years_of_experience=4.0)
    in_range = WeightedFactorEngine()._experience_factor(resume, _position())
    assert in_range == 1.0
    below = ResumeMatchProfile(raw_text="x", skills=set(), years_of_experience=1.0)
    assert WeightedFactorEngine()._experience_factor(below, _position()) < 1.0
    no_req = _position(experience_req="经验不限")
    assert WeightedFactorEngine()._experience_factor(resume, no_req) == 0.5


def test_city_and_salary_factors() -> None:
    engine = WeightedFactorEngine(intention=JobIntention(city="深圳", salary_min=20000, salary_max=30000))
    assert engine._city_factor(_position()) == 1.0
    assert engine._city_factor(_position(city="上海")) == 0.0
    assert engine._salary_factor(_position()) == 1.0
    assert engine._salary_factor(_position(salary_min=40000, salary_max=50000)) == 0.0
    # 职位薪资为空 → 中性放行
    assert engine._salary_factor(_position(salary_min=None, salary_max=None)) == 0.5


def test_build_resume_profile_extracts_skills_and_years() -> None:
    engine = WeightedFactorEngine()
    profile = engine.build_resume_profile(
        ResumeRawText(text="精通 Java 与 Python，3年经验，熟悉 Docker 和 MySQL", parseable=True)
    )
    assert "java" in profile.skills
    assert "python" in profile.skills
    assert "docker" in profile.skills
    assert profile.years_of_experience == 3.0


def test_weights_are_configurable() -> None:
    engine = WeightedFactorEngine(weights={"skill": 1.0, "experience": 0.0, "city": 0.0, "salary": 0.0})
    resume = ResumeMatchProfile(raw_text="x", skills={"java"}, years_of_experience=None)
    hit = engine.compute_score(resume, _position())
    miss = engine.compute_score(resume, _position(title="销售经理", experience_req="1-3年"))
    assert hit.value == 100
    assert miss.value == 0