"""可控模拟平台适配器：支持注入四类场景（成功/网络超时/限流风控/授权过期），
并提供可配置的职位数据集与状态回执队列，用于开发与测试。
demo_data=True 时预置演示职位数据集（开箱即用体验完整流程）。
"""

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
    """演示职位数据集：30 家公司轮换 10 类岗位，覆盖各城市/行业/薪资档位/经验档位。

    行业名与前端 FILTER_INDUSTRY_OPTIONS 精确对齐（互联网/电商/游戏/硬件/医疗/物流/制造业/房地产/咨询/传媒）。
    """
    companies = [
        ("腾讯", "互联网", "深圳"), ("阿里巴巴", "互联网", "杭州"), ("字节跳动", "互联网", "北京"),
        ("美团", "互联网", "北京"), ("京东", "电商", "北京"), ("百度", "互联网", "北京"),
        ("网易", "游戏", "杭州"), ("拼多多", "电商", "上海"), ("哔哩哔哩", "互联网", "上海"),
        ("携程", "互联网", "上海"), ("华为", "硬件", "深圳"), ("大疆", "硬件", "深圳"),
        ("招商银行", "金融", "深圳"), ("平安保险", "金融", "深圳"), ("东方财富", "金融", "上海"),
        ("新东方", "教育", "北京"), ("好未来", "教育", "北京"), ("猿辅导", "教育", "北京"),
        ("迈瑞医疗", "医疗", "深圳"), ("药明康德", "医疗", "上海"), ("顺丰速运", "物流", "深圳"),
        ("满帮集团", "物流", "南京"), ("比亚迪", "制造业", "深圳"), ("格力电器", "制造业", "珠海"),
        ("万科地产", "房地产", "深圳"), ("链家", "房地产", "北京"), ("埃森哲", "咨询", "上海"),
        ("分众传媒", "传媒", "上海"), ("小红书", "互联网", "上海"), ("米哈游", "游戏", "上海"),
    ]
    roles = [
        ("Java 开发工程师", "3-5年", 15000, 30000),
        ("Python 后端工程师", "3-5年", 15000, 28000),
        ("前端开发工程师", "1-3年", 12000, 25000),
        ("测试工程师", "1-3年", 10000, 20000),
        ("产品经理", "3-5年", 18000, 35000),
        ("运营专员", "应届", 6000, 12000),
        ("算法工程师", "5-10年", 30000, 60000),
        ("数据分析师", "1-3年", 12000, 22000),
        ("行政助理", "1-3年", 3000, 5000),
        ("技术总监", "10年以上", 50000, 80000),
    ]
    expire = datetime.now() + timedelta(days=30)
    positions = []
    for i, (company, industry, city) in enumerate(companies):
        title, exp, smin, smax = roles[i % len(roles)]
        positions.append(
            PositionDTO(
                position_id=f"demo_{i + 1}",
                platform_id="mock_platform",
                title=title,
                company=company,
                city=city,
                salary_min=smin,
                salary_max=smax,
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