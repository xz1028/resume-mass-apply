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
    """程序化生成演示职位数据集（约 430 个职位，固定种子保证确定性）。

    设计目标：让每个筛选维度都有足量命中——
    - 城市：覆盖前端 FILTER_CITY_OPTIONS 全部 23 城
    - 行业：12 行业全覆盖（与前端选项精确对齐）
    - 薪资：覆盖 3K以下/3-5K/5-10K/10-20K/20-50K/50K+ 全部档位
    - 经验：覆盖 应届/1-3年/3-5年/5-10年/10年以上/不限 全部档位
    - 关键词：Java/Python/前端/测试/产品/运营/算法/数据分析 均有命中
    """
    rng = _random.Random(2026)

    industry_companies = {
        "互联网": [("腾讯", "深圳"), ("阿里巴巴", "杭州"), ("字节跳动", "北京"), ("美团", "北京"), ("百度", "北京"), ("哔哩哔哩", "上海"), ("小红书", "上海"), ("携程", "上海"), ("知乎", "北京"), ("快手", "北京")],
        "电商": [("京东", "北京"), ("拼多多", "上海"), ("淘天集团", "杭州"), ("唯品会", "广州"), ("得物", "上海"), ("苏宁易购", "南京"), ("希音", "广州"), ("途虎养车", "上海")],
        "游戏": [("网易", "杭州"), ("米哈游", "上海"), ("莉莉丝", "上海"), ("完美世界", "北京"), ("三七互娱", "广州"), ("吉比特", "厦门"), ("巨人网络", "上海"), ("西山居", "珠海")],
        "金融": [("招商银行", "深圳"), ("平安保险", "深圳"), ("东方财富", "上海"), ("华泰证券", "南京"), ("广发基金", "广州"), ("陆金所", "上海"), ("同花顺", "杭州"), ("湘财证券", "长沙")],
        "教育": [("新东方", "北京"), ("好未来", "北京"), ("猿辅导", "北京"), ("作业帮", "北京"), ("学而思", "北京"), ("中公教育", "北京"), ("华图教育", "北京"), ("粉笔科技", "北京")],
        "医疗": [("迈瑞医疗", "深圳"), ("药明康德", "上海"), ("联影医疗", "上海"), ("微创医疗", "上海"), ("爱尔眼科", "长沙"), ("通策医疗", "杭州"), ("金域医学", "广州"), ("万孚生物", "广州")],
        "硬件": [("华为", "深圳"), ("大疆", "深圳"), ("OPPO", "深圳"), ("vivo", "深圳"), ("小米", "北京"), ("联想", "北京"), ("海尔", "青岛"), ("TCL", "惠州")],
        "制造业": [("比亚迪", "深圳"), ("格力电器", "珠海"), ("宁德时代", "宁波"), ("三一重工", "长沙"), ("徐工集团", "南京"), ("美的集团", "佛山"), ("中联重科", "长沙"), ("福耀玻璃", "福州")],
        "房地产": [("万科地产", "深圳"), ("保利发展", "广州"), ("龙湖集团", "北京"), ("链家", "北京"), ("贝壳", "北京"), ("我爱我家", "北京"), ("中原地产", "上海"), ("世联行", "深圳")],
        "咨询": [("埃森哲", "上海"), ("麦肯锡", "上海"), ("波士顿咨询", "上海"), ("德勤", "上海"), ("普华永道", "上海"), ("毕马威", "北京"), ("君合律所", "北京"), ("中金公司", "北京")],
        "传媒": [("分众传媒", "上海"), ("芒果超媒", "长沙"), ("光线传媒", "北京"), ("华策影视", "杭州"), ("中文在线", "北京"), ("掌阅科技", "北京"), ("值得买", "北京"), ("阅文集团", "上海")],
        "物流": [("顺丰速运", "深圳"), ("满帮集团", "南京"), ("京东物流", "北京"), ("菜鸟网络", "杭州"), ("中通快递", "上海"), ("圆通速递", "上海"), ("极兔速递", "上海"), ("德邦物流", "上海")],
    }

    # 技术岗池：仅科技类行业大量招募（互联网/电商/游戏/硬件）
    tech_roles = [
        ("Java 开发工程师", "3-5年", 15, 30),
        ("Python 后端工程师", "3-5年", 15, 28),
        ("前端开发工程师", "1-3年", 12, 25),
        ("测试工程师", "1-3年", 10, 20),
        ("算法工程师", "5-10年", 30, 60),
        ("数据分析师", "1-3年", 12, 22),
        ("产品经理", "3-5年", 18, 35),
        ("运维工程师", "1-3年", 10, 20),
        ("UI 设计师", "1-3年", 8, 16),
        ("架构师", "5-10年", 40, 70),
        ("技术总监", "10年以上", 50, 80),
    ]
    # 职能岗池（非 IT）：所有行业通用，传统行业的主要补充岗源
    generic_roles = [
        ("行政助理", "1-3年", 3, 5),
        ("HR 专员", "1-3年", 5, 9),
        ("财务会计", "3-5年", 8, 15),
        ("销售代表", "应届", 3, 8),
        ("客服专员", "应届", 3, 6),
        ("采购专员", "1-3年", 5, 9),
        ("市场专员", "1-3年", 6, 12),
        ("法务专员", "3-5年", 10, 18),
        ("翻译专员", "1-3年", 7, 14),
        ("商务拓展", "1-3年", 8, 16),
        ("储备干部", "应届", 5, 10),
        ("仓库管理员", "1-3年", 3, 5),
        ("实习生", "经验不限", 2, 3),
    ]
    tech_industries = {"互联网", "电商", "游戏", "硬件"}

    industry_roles = {
        "互联网": [("客户端开发工程师", "3-5年", 18, 35), ("大数据工程师", "3-5年", 20, 40), ("云计算工程师", "3-5年", 20, 38), ("安全工程师", "3-5年", 18, 35), ("运维工程师", "1-3年", 10, 20)],
        "电商": [("电商运营", "1-3年", 8, 16), ("选品专员", "1-3年", 6, 12), ("直播运营", "1-3年", 8, 18), ("供应链专员", "1-3年", 8, 15), ("品类运营", "3-5年", 12, 24)],
        "游戏": [("游戏策划", "1-3年", 10, 22), ("游戏原画师", "1-3年", 10, 20), ("Unity 开发工程师", "3-5年", 15, 30), ("数值策划", "3-5年", 15, 28), ("技术美术", "3-5年", 18, 32)],
        "金融": [("证券分析师", "3-5年", 15, 35), ("风控专员", "1-3年", 10, 20), ("理财顾问", "1-3年", 8, 18), ("量化研究员", "5-10年", 30, 60), ("银行柜员", "应届", 5, 9)],
        "教育": [("课程顾问", "应届", 5, 10), ("学科教师", "1-3年", 8, 18), ("教研员", "3-5年", 12, 24), ("班主任", "1-3年", 6, 12), ("少儿编程讲师", "1-3年", 8, 16)],
        "医疗": [("临床研究员", "3-5年", 12, 25), ("医药代表", "1-3年", 8, 18), ("医疗器械注册专员", "3-5年", 12, 22), ("护士", "1-3年", 5, 10), ("医学编辑", "1-3年", 7, 14)],
        "硬件": [("嵌入式工程师", "3-5年", 15, 30), ("硬件测试工程师", "1-3年", 10, 20), ("射频工程师", "3-5年", 18, 35), ("芯片设计工程师", "5-10年", 30, 60), ("结构工程师", "3-5年", 12, 25)],
        "制造业": [("工艺工程师", "3-5年", 10, 20), ("质量工程师", "3-5年", 10, 20), ("设备维护工程师", "1-3年", 7, 14), ("生产计划员", "1-3年", 6, 12), ("自动化工程师", "3-5年", 12, 24)],
        "房地产": [("置业顾问", "应届", 5, 12), ("工程造价师", "3-5年", 12, 22), ("物业管家", "1-3年", 5, 9), ("招商专员", "1-3年", 8, 16), ("土建工程师", "3-5年", 12, 24)],
        "咨询": [("管理咨询顾问", "应届", 10, 20), ("商业分析师", "1-3年", 12, 25), ("审计助理", "应届", 8, 15), ("税务顾问", "3-5年", 15, 30), ("合规顾问", "3-5年", 15, 28)],
        "传媒": [("新媒体运营", "1-3年", 7, 15), ("视频剪辑师", "1-3年", 8, 16), ("文案策划", "1-3年", 7, 14), ("主播运营", "1-3年", 8, 18), ("编剧", "3-5年", 12, 25)],
        "物流": [("物流规划师", "3-5年", 12, 24), ("调度专员", "1-3年", 7, 14), ("车队管理", "3-5年", 10, 20), ("报关员", "1-3年", 7, 14), ("仓储主管", "3-5年", 10, 18)],
    }

    extra_cities = ["成都", "武汉", "西安", "苏州", "郑州", "济南", "天津", "合肥", "青岛", "佛山", "东莞"]
    expire = datetime.now() + timedelta(days=30)
    positions: list[PositionDTO] = []
    seq = 0

    for industry, companies in industry_companies.items():
        # 岗位池按行业属性分配：科技行业大量招技术岗；传统行业以本行业岗 + 职能岗为主
        base_pool = tech_roles if industry in tech_industries else generic_roles
        industry_pool = base_pool + industry_roles[industry]
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