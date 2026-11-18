"""可控模拟平台适配器：支持注入四类场景（成功/网络超时/限流风控/授权过期），
并提供可配置的职位数据集与状态回执队列，用于开发与测试。
demo_data=True 时预置演示职位数据集（开箱即用体验完整流程）。
"""

import random as _random
from datetime import datetime, timedelta

from app.domain.models import AuthStatus, ContactInfo, DeliveryStatus, JobIntention
from app.platforms.spi import (
    ApplyResult,
    EncryptedResumeRef,
    PlatformAdapter,
    PlatformAuthExpiredError,
    PlatformRateLimitedError,
    PlatformRecordRef,
    PlatformUnavailableError,
    PositionDTO,
    RateLimitPolicy,
    StatusReceipt,
)

SCENARIO_SUCCESS = "success"
SCENARIO_TIMEOUT = "timeout"
SCENARIO_RATE_LIMITED = "rate_limited"
SCENARIO_AUTH_EXPIRED = "auth_expired"
SCENARIO_UNAVAILABLE = "unavailable"


def _build_demo_positions() -> list[PositionDTO]:
    """程序化生成演示职位数据集（固定种子保证确定性，实测恰好 585 个职位）。

    数据源：app/platforms/demo_data/ 白名单三文件（companies/industry_roles/city_salary），
    loader 加载失败时拒绝生成（无回退无约束生成）。

    设计目标：让每个筛选维度都有足量命中——
    - 城市：覆盖前端 FILTER_CITY_OPTIONS 全部 23 城
    - 行业：12 行业全覆盖（与前端选项精确对齐）
    - 薪资：覆盖 3K以下/3-5K/5-10K/10-20K/20-50K/50K+ 全部档位，且落在城市档位区间内
    - 经验：覆盖 应届/1-3年/3-5年/5-10年/10年以上/不限 全部档位
    - 关键词：Java/Python/前端/测试/产品/运营/算法/数据分析 均有命中

    输出不变性硬约束：行业顺序、公司顺序、种子 2026、随机采样逻辑与改造前逐行一致
    （城市档位 clamp 不消耗随机数），确保数量与结构不变（design 1.2.5）。
    """
    from app.platforms.demo_data.loader import WHITELIST, clamp_salary_to_city

    rng = _random.Random(2026)

    industry_companies = WHITELIST["companies"]
    tech_roles = WHITELIST["tech_roles"]
    generic_roles = WHITELIST["generic_roles"]
    tech_industries = WHITELIST["tech_industries"]
    industry_roles_map = WHITELIST["industry_roles"]
    city_bands = WHITELIST["city_bands"]

    extra_cities = ["成都", "武汉", "西安", "苏州", "郑州", "济南", "天津", "合肥", "青岛", "佛山", "东莞"]
    expire = datetime.now() + timedelta(days=30)
    positions: list[PositionDTO] = []
    seq = 0

    for industry, companies in industry_companies.items():
        # 岗位池按行业属性分配：科技行业大量招技术岗；传统行业以本行业岗 + 职能岗为主
        base_pool = tech_roles if industry in tech_industries else generic_roles
        industry_pool = base_pool + industry_roles_map[industry]
        for company, hq_city in companies:
            role_count = rng.randint(5, 7)
            chosen = rng.sample(industry_pool, min(role_count, len(industry_pool)))
            for title, exp, smin_k, smax_k in chosen:
                seq += 1
                salary_min = int(smin_k * 1000 * rng.uniform(0.92, 1.08))
                salary_max = int(smax_k * 1000 * rng.uniform(0.95, 1.1))
                if salary_max <= salary_min:
                    salary_max = salary_min + 2000
                city = hq_city if rng.random() < 0.65 else rng.choice(extra_cities + [hq_city])
                # 城市薪资档位约束：扰动结果按城市档位区间 clamp（不消耗随机数）
                salary_min, salary_max = clamp_salary_to_city(
                    salary_min, salary_max, city_bands[city]
                )
                positions.append(
                    PositionDTO(
                        position_id=f"demo_{seq}",
                        platform_id="mock_platform",
                        title=title,
                        company=company,
                        city=city,
                        salary_min=salary_min,
                        salary_max=salary_max,
                        industry=industry,
                        experience_req=exp,
                        publish_expire_at=expire,
                    )
                )
    return positions


class MockAdapter:
    """实现 PlatformAdapter 全部四方法，通过 Protocol 结构化子类型通过类型检查。"""

    platform_id: str
    rate_limit: RateLimitPolicy

    def __init__(
        self,
        platform_id: str = "mock_platform",
        name: str = "模拟招聘平台",
        max_per_hour: float = 30.0,
        demo_data: bool = False,
    ) -> None:
        self.platform_id = platform_id
        self.name = name
        self.rate_limit = RateLimitPolicy(max_per_hour=max_per_hour)
        self._positions: list[PositionDTO] = _build_demo_positions() if demo_data else []
        self._seq = 0
        # 场景注入
        self.fetch_scenario: str = SCENARIO_SUCCESS
        self.submit_scenario: str = SCENARIO_SUCCESS
        self.submit_scenarios_queue: list[str] = []  # 逐次消费的一次性场景
        self.valid_credentials: set[str] = {"valid-token"}
        self.status_receipts: dict[str, list[StatusReceipt]] = {}
        # 调用记录（供测试断言）
        self.submitted: list[tuple[PositionDTO, ContactInfo]] = []
        self.fetch_calls: list[JobIntention] = []

    # ---- 测试辅助 ----

    def set_positions(self, positions: list[PositionDTO]) -> None:
        self._positions = list(positions)

    def queue_status_receipt(self, platform_record_ref: str, receipt: StatusReceipt) -> None:
        self.status_receipts.setdefault(platform_record_ref, []).append(receipt)

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---- PlatformAdapter 契约实现 ----

    def fetch_positions(self, intent: JobIntention, since: datetime) -> list[PositionDTO]:
        """返回全部配置职位数据集（意向参数记录在 fetch_calls 供断言；过滤由上层筛选完成）。"""
        self.fetch_calls.append(intent)
        if self.fetch_scenario == SCENARIO_UNAVAILABLE:
            raise PlatformUnavailableError(f"{self.platform_id} 职位接口不可用（模拟超时/5xx）")
        return list(self._positions)

    def submit_application(
        self,
        position: PositionDTO,
        resume_file: EncryptedResumeRef,
        contact: ContactInfo,
        greeting: str | None = None,
    ) -> ApplyResult:
        self.submitted.append((position, contact))
        now = datetime.now()
        scenario = self.submit_scenario
        if self.submit_scenarios_queue:
            scenario = self.submit_scenarios_queue.pop(0)
        if scenario == SCENARIO_TIMEOUT:
            raise PlatformUnavailableError(f"{self.platform_id} 投递接口超时（模拟 5xx）")
        if scenario == SCENARIO_RATE_LIMITED:
            raise PlatformRateLimitedError(f"{self.platform_id} 触发平台限流/风控")
        if scenario == SCENARIO_AUTH_EXPIRED:
            raise PlatformAuthExpiredError(f"{self.platform_id} 授权已过期")
        return ApplyResult(
            success=True,
            platform_record_ref=f"{self.platform_id}-{position.position_id}-{self.next_seq()}",
            receipt_time=now,
            receipt_seq=self._seq,
        )

    def fetch_application_status(
        self, record_refs: list[PlatformRecordRef]
    ) -> list[StatusReceipt]:
        receipts: list[StatusReceipt] = []
        for ref in record_refs:
            queue = self.status_receipts.get(ref.platform_record_ref)
            if queue:
                receipts.append(queue.pop(0))
        return receipts

    def validate_authorization(self, credential: str) -> AuthStatus:
        if credential in self.valid_credentials:
            return AuthStatus.authorized
        return AuthStatus.unauthorized