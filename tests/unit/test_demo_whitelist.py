"""演示数据白名单单元测试（tasks 1.6）：加载/校验拒绝/生成不变性/三重校验。"""

import json

import pytest

from app.platforms.demo_data.loader import (
    DemoDataError,
    _data_dir,
    clamp_salary_to_city,
    load_all,
)


class TestWhitelistLoading:
    def test_three_files_loaded_successfully(self):
        data = load_all()
        assert set(data) == {
            "companies", "tech_roles", "generic_roles", "tech_industries", "industry_roles", "city_bands",
        }
        assert len(data["companies"]) == 12
        total_companies = sum(len(v) for v in data["companies"].values())
        assert 90 <= total_companies <= 110
        assert len(data["city_bands"]) >= 23

    def test_company_industry_uniqueness(self):
        data = load_all()
        names = [name for pairs in data["companies"].values() for name, _ in pairs]
        assert len(names) == len(set(names))

    def test_module_import_loads_once(self):
        from app.platforms.demo_data import loader

        assert loader.WHITELIST == load_all() or len(loader.WHITELIST["companies"]) == 12


class TestWhitelistValidationRejections:
    """结构化校验失败必须拒绝生成（禁止回退无约束生成）。"""

    VALID_MINIMAL_ROLES = {
        "tech_roles": [{"title": "技术岗", "experience": "1-3年", "salary_min_k": 10, "salary_max_k": 20}],
        "generic_roles": [{"title": "职能岗", "experience": "应届", "salary_min_k": 3, "salary_max_k": 6}],
        "tech_industries": ["互联网"],
        "industry_roles": {"互联网": [{"title": "行业岗", "experience": "1-3年", "salary_min_k": 5, "salary_max_k": 10}]},
    }

    def _write_and_load(self, tmp_path, filename, content):
        target = tmp_path
        for chunk in ("companies.json", "industry_roles.json", "city_salary.json"):
            if chunk == filename:
                (target / chunk).write_text(
                    json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content),
                    encoding="utf-8",
                )
            elif not (target / chunk).exists():
                (target / chunk).write_text("{}", encoding="utf-8")

    def test_missing_file_rejected(self, tmp_path, monkeypatch):
        (tmp_path / "industry_roles.json").write_text("{}", encoding="utf-8")
        (tmp_path / "city_salary.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("app.platforms.demo_data.loader._data_dir", lambda: tmp_path)
        with pytest.raises(DemoDataError, match="缺失"):
            load_all()

    def test_industry_map_must_be_dict(self, tmp_path, monkeypatch):
        (tmp_path / "industry_roles.json").write_text('{"industry_roles": []}', encoding="utf-8")
        self._write_and_load(tmp_path, "companies.json", {"industries": [{"industry": "互联网", "companies": [{"name": "A", "hq_city": "北京"}]}]})
        (tmp_path / "city_salary.json").write_text('{"bands": [{"cities": ["北京"], "min_k": 1, "max_k": 100}]}', encoding="utf-8")
        monkeypatch.setattr("app.platforms.demo_data.loader._data_dir", lambda: tmp_path)
        with pytest.raises(DemoDataError, match="industry_roles"):
            load_all()

    def test_duplicate_company_across_industries_rejected(self, tmp_path, monkeypatch):
        self._write_and_load(
            tmp_path,
            "companies.json",
            {
                "industries": [
                    {"industry": "互联网", "companies": [{"name": "同公司", "hq_city": "北京"}]},
                    {"industry": "金融", "companies": [{"name": "同公司", "hq_city": "上海"}]},
                ]
            },
        )
        self._write_and_load(tmp_path, "industry_roles.json", self.VALID_MINIMAL_ROLES)
        self._write_and_load(tmp_path, "city_salary.json", {"bands": [{"cities": ["北京", "上海"], "min_k": 1, "max_k": 100}]})
        monkeypatch.setattr("app.platforms.demo_data.loader._data_dir", lambda: tmp_path)
        with pytest.raises(DemoDataError, match="公司行业归属冲突"):
            load_all()

    def test_invalid_salary_band_rejected(self, tmp_path, monkeypatch):
        self._write_and_load(tmp_path, "companies.json", {"industries": [{"industry": "互联网", "companies": [{"name": "A", "hq_city": "北京"}]}]})
        self._write_and_load(tmp_path, "industry_roles.json", self.VALID_MINIMAL_ROLES)
        self._write_and_load(tmp_path, "city_salary.json", {"bands": [{"cities": ["北京"], "min_k": 50, "max_k": 10}]})
        monkeypatch.setattr("app.platforms.demo_data.loader._data_dir", lambda: tmp_path)
        with pytest.raises(DemoDataError, match="档位区间非法"):
            load_all()

    def test_uncovered_hq_city_rejected(self, tmp_path, monkeypatch):
        self._write_and_load(tmp_path, "companies.json", {"industries": [{"industry": "互联网", "companies": [{"name": "A", "hq_city": "北京"}]}]})
        self._write_and_load(tmp_path, "industry_roles.json", self.VALID_MINIMAL_ROLES)
        self._write_and_load(tmp_path, "city_salary.json", {"bands": [{"cities": ["上海"], "min_k": 1, "max_k": 100}]})
        monkeypatch.setattr("app.platforms.demo_data.loader._data_dir", lambda: tmp_path)
        with pytest.raises(DemoDataError, match="未覆盖公司总部城市"):
            load_all()



class TestGeneratorInvariance:
    """输出不变性硬约束：恰好 585 条 + 三重校验全绿（design 1.2.5）。"""

    def test_positions_count_exactly_585(self):
        from app.platforms.mock_adapter import _build_demo_positions

        assert len(_build_demo_positions()) == 585

    def test_all_positions_pass_triple_validation(self):
        from app.platforms.mock_adapter import _build_demo_positions

        whitelist = load_all()
        valid_pairs = {
            (industry, name)
            for industry, pairs in whitelist["companies"].items()
            for name, _ in pairs
        }
        role_map: dict[str, set] = {}
        for industry, rows in whitelist["industry_roles"].items():
            role_map[industry] = {r[0] for r in rows}
        for industry in whitelist["tech_industries"]:
            role_map.setdefault(industry, set()).update(r[0] for r in whitelist["tech_roles"])
        for industry in whitelist["companies"]:
            role_map.setdefault(industry, set()).update(r[0] for r in whitelist["generic_roles"])

        for p in _build_demo_positions():
            assert (p.industry, p.company) in valid_pairs, f"公司行业归属非法: {p.company}"
            assert p.title in role_map.get(p.industry, set()), f"岗位不属于行业池: {p.title}/{p.industry}"
            band = whitelist["city_bands"][p.city]
            assert band[0] <= p.salary_min <= p.salary_max <= band[1], f"薪资越城市档位: {p.city}"

    def test_mock_adapter_without_demo_data_unaffected(self, test_env):
        """conftest 的 MockAdapter()（demo_data=False）路径回归断言。"""
        mock = test_env.mock
        assert mock._positions == []
        assert mock.platform_id == "mock_platform"


class TestSalaryClamp:
    def test_clamp_within_band(self):
        assert clamp_salary_to_city(8000, 25000, (5000, 100000)) == (8000, 25000)

    def test_clamp_below_floor(self):
        lo, hi = clamp_salary_to_city(2000, 3000, (5000, 100000))
        assert lo >= 5000 and hi > lo

    def test_clamp_above_ceiling(self):
        lo, hi = clamp_salary_to_city(90000, 120000, (5000, 80000))
        assert lo <= 80000 and hi <= 80000 and lo <= hi

    def test_clamp_equal_bounds_fallback(self):
        lo, hi = clamp_salary_to_city(80000, 79000, (5000, 80000))
        assert lo <= hi