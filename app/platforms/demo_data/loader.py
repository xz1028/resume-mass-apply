"""演示数据白名单加载与结构化校验（模块导入期加载一次）。

三文件（companies / industry_roles / city_salary）任一缺失或结构非法时
抛 DemoDataError 并记录明确错误日志——禁止回退无约束生成（spec 5.3.3.1）。
路径解析兼容开发者形态与 PyInstaller frozen 形态（sys._MEIPASS 优先）。
"""

import json
import sys
from pathlib import Path

from app.infra.logging import get_logger

logger = get_logger("demo_whitelist")


class DemoDataError(Exception):
    """白名单数据缺失或结构非法。"""


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).parent)
        candidate = base / "app" / "platforms" / "demo_data"
        if candidate.is_dir():
            return candidate
    return Path(__file__).parent


def _load_json(name: str) -> dict:
    path = _data_dir() / name
    if not path.is_file():
        raise DemoDataError(f"演示数据白名单缺失: {path}")
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise DemoDataError(f"演示数据白名单损坏（JSON 解析失败）: {name}: {exc}") from exc


def _validate_companies(data: dict) -> dict:
    industries = data.get("industries")
    if not isinstance(industries, list) or not industries:
        raise DemoDataError("companies.json 缺少非空 industries 数组")
    seen_names: set[str] = set()
    result: dict[str, list[tuple[str, str]]] = {}
    for block in industries:
        industry = block.get("industry")
        companies = block.get("companies")
        if not industry or not isinstance(companies, list) or not companies:
            raise DemoDataError(f"companies.json 行业块非法: {industry!r}")
        pairs = []
        for company in companies:
            name = company.get("name")
            hq_city = company.get("hq_city")
            if not name or not hq_city:
                raise DemoDataError(f"companies.json 公司字段非法: {company!r}")
            if name in seen_names:
                raise DemoDataError(f"公司行业归属冲突（同名公司出现于多个行业）: {name}")
            seen_names.add(name)
            pairs.append((name, hq_city))
        result[industry] = pairs
    if not seen_names:
        raise DemoDataError("companies.json 无任何公司")
    return result


def _validate_roles(data: dict) -> tuple:
    tech_raw = data.get("tech_roles")
    generic_raw = data.get("generic_roles")
    tech_industries = data.get("tech_industries")
    industry_roles_raw = data.get("industry_roles")
    for field, value in (
        ("tech_roles", tech_raw),
        ("generic_roles", generic_raw),
        ("tech_industries", tech_industries),
    ):
        if not isinstance(value, list) or not value:
            raise DemoDataError(f"industry_roles.json 缺少非空 {field}")
    if not isinstance(industry_roles_raw, dict) or not industry_roles_raw:
        raise DemoDataError("industry_roles.json 缺少非空 industry_roles 映射")

    def _convert(rows: list) -> list[tuple[str, str, int, int]]:
        converted = []
        for row in rows:
            title = row.get("title")
            experience = row.get("experience")
            smin = row.get("salary_min_k")
            smax = row.get("salary_max_k")
            if not title or not experience:
                raise DemoDataError(f"industry_roles.json 岗位字段非法: {row!r}")
            if not isinstance(smin, (int, float)) or not isinstance(smax, (int, float)) or smin > smax:
                raise DemoDataError(f"industry_roles.json 岗位薪资基准非法（下限高于上限）: {title}")
            converted.append((title, experience, smin, smax))
        return converted

    tech_roles = _convert(tech_raw)
    generic_roles = _convert(generic_raw)
    industry_roles: dict[str, list[tuple[str, str, int, int]]] = {}
    for industry, rows in industry_roles_raw.items():
        if not isinstance(rows, list) or not rows:
            raise DemoDataError(f"industry_roles.json 行业岗位集合为空: {industry}")
        industry_roles[industry] = _convert(rows)
    return tech_roles, generic_roles, set(tech_industries), industry_roles


def _validate_city_salary(data: dict) -> dict[str, tuple[int, int]]:
    bands = data.get("bands")
    if not isinstance(bands, list) or not bands:
        raise DemoDataError("city_salary.json 缺少非空 bands 数组")
    result: dict[str, tuple[int, int]] = {}
    seen_cities: set[str] = set()
    for band in bands:
        cities = band.get("cities")
        min_k = band.get("min_k")
        max_k = band.get("max_k")
        if not isinstance(cities, list) or not cities:
            raise DemoDataError(f"city_salary.json 档位城市列表为空: {band.get('label')!r}")
        if not isinstance(min_k, (int, float)) or not isinstance(max_k, (int, float)) or min_k > max_k or min_k <= 0:
            raise DemoDataError(f"city_salary.json 档位区间非法（下限高于上限或非正）: {band.get('label')!r}")
        for city in cities:
            if city in seen_cities:
                raise DemoDataError(f"city_salary.json 城市归属冲突（同城市出现于多个档位）: {city}")
            seen_cities.add(city)
            result[city] = (int(min_k * 1000), int(max_k * 1000))
    return result


def load_all() -> dict:
    """加载并校验三文件；失败时记录明确错误并抛 DemoDataError。"""
    try:
        companies = _validate_companies(_load_json("companies.json"))
        tech_roles, generic_roles, tech_industries, industry_roles = _validate_roles(
            _load_json("industry_roles.json")
        )
        city_bands = _validate_city_salary(_load_json("city_salary.json"))
    except DemoDataError as exc:
        logger.error("demo_whitelist_invalid", reason=str(exc))
        raise
    missing = []
    for industry, pairs in companies.items():
        for _name, hq_city in pairs:
            if hq_city not in city_bands:
                missing.append(f"{industry}/{hq_city}")
    if missing:
        raise DemoDataError(f"city_salary.json 未覆盖公司总部城市: {', '.join(missing[:5])}")
    logger.info(
        "demo_whitelist_loaded",
        companies=sum(len(v) for v in companies.values()),
        industries=len(companies),
        cities=len(city_bands),
    )
    return {
        "companies": companies,
        "tech_roles": tech_roles,
        "generic_roles": generic_roles,
        "tech_industries": tech_industries,
        "industry_roles": industry_roles,
        "city_bands": city_bands,
    }


WHITELIST = load_all()


def clamp_salary_to_city(salary_min: int, salary_max: int, band: tuple[int, int]) -> tuple[int, int]:
    """岗位基准 ± 扰动结果按城市档位 clamp（spec 5.3 城市薪资档位约束）。"""
    band_lo, band_hi = band
    clamped_min = max(band_lo, min(salary_min, band_hi))
    clamped_max = max(band_lo, min(salary_max, band_hi))
    if clamped_max <= clamped_min:
        clamped_max = min(band_hi, clamped_min + 2000)
        if clamped_max <= clamped_min:
            clamped_min = band_lo
            clamped_max = min(band_hi, band_lo + 2000)
            clamped_min = min(clamped_min, clamped_max)
    return clamped_min, clamped_max