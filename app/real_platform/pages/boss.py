"""BOSS直聘页面对象常量：URL 模式、多候选选择器、状态映射、检索参数映射。

平台改版时仅修改本模块与对应适配器，禁改 SPI 契约与上层。
"""

from app.domain.models import DeliveryStatus

PLATFORM_ID = "boss_zhipin"
PLATFORM_NAME = "BOSS直聘"

LOGIN_URL = "https://www.zhipin.com/?ka=header-login"
SEARCH_URL_TEMPLATE = "https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}"
DETAIL_URL_PATTERN = "https://www.zhipin.com/job_detail/"
CHAT_URL_PATTERN = "https://www.zhipin.com/web/geek/chat"
MY_MESSAGE_URL = "https://www.zhipin.com/web/geek/recommend"

CITY_CODE_MAP = {
    "北京": "101010100", "上海": "101020100", "深圳": "101280600", "广州": "101280100",
    "杭州": "101210100", "成都": "101270100", "武汉": "101200100", "南京": "101190100",
    "西安": "101110100", "长沙": "101250100", "苏州": "101190400", "东莞": "101281600",
    "佛山": "101280800", "重庆": "101040100", "郑州": "101180100", "宁波": "101210400",
    "厦门": "101230200", "青岛": "101200200", "天津": "101030100", "济南": "10110100",
    "合肥": "101220100", "福州": "101230100", "珠海": "101280700",
}

# 登录态特征（出现即视为已登录）
LOGIN_STATE_SELECTORS = [
    "[data-selector*='user']",
    ".user-info",
    "a[href*='/web/geek/recommend']",
    ".btn-start-chat",
]

# 搜索结果容器与卡片字段
RESULT_CONTAINER_SELECTORS = [".job-list-box", ".job-list", "[ka='job-list']"]
CARD_SELECTORS = [".job-card-wrapper", ".job-card", "li.job-card"]
CARD_TITLE_SELECTORS = [".job-title", ".job-name", "h3"]
CARD_COMPANY_SELECTORS = [".company-info a", ".company-name", "[ka='search_list_company_name']"]
CARD_SALARY_SELECTORS = [".salary", ".job-salary"]
CARD_CITY_SELECTORS = [".job-area", ".info-desc", ".job-area-wrapper"]
CARD_LINK_SELECTORS = ["a.job-card-left", ".job-card-inner a", "a[ka^='search_list_job']"]

# 详情页
DETAIL_CONTAINER_SELECTORS = [".job-detail-box", ".job-detail", ".job-sec"]
DETAIL_PUBLISH_TIME_SELECTORS = [".job-publish-time", ".time"]

# 投递动作（沟通制：立即沟通→聊天窗口发送招呼）
CHAT_BUTTON_SELECTORS = [".op-btn-chat", "[ka='job_detail_chat']", ".btn-start-chat"]
GREETING_SEND_SELECTORS = [".chat-input", ".chat-message-input", "textarea"]
GREETING_SEND_BUTTON_SELECTORS = [".send-btn", "[ka='send_message']"]

# 已投递信号（幂等判定）
ALREADY_APPLIED_SELECTORS = [".btn-start-chat.disabled", ".chat-started", "[ka='job_detail_chat'].disabled"]
ALREADY_APPLIED_TEXTS = ["继续沟通", "已沟通", "聊天中"]

# 验证码特征
CAPTCHA_URL_HINTS = ["verify", "captcha", "security-check"]
CAPTCHA_CONTAINER_SELECTORS = [".captcha-box", "#captcha", ".verify-dialog", ".geetest_box"]

# 风控关键词（登录页 URL 提示 = 登录态失效）
LOGIN_URL_MARKS = ["login", "signin", "passport"]

# 状态标签 → DeliveryStatus（消息/沟通列表解析）
STATUS_LABEL_MAP = {
    "已读": DeliveryStatus.viewed,
    "HR 已读": DeliveryStatus.viewed,
    "已查看": DeliveryStatus.viewed,
    "面试邀请": DeliveryStatus.interview_invited,
    "邀约": DeliveryStatus.interview_invited,
    "约面试": DeliveryStatus.interview_invited,
    "不合适": DeliveryStatus.rejected,
    "婉拒": DeliveryStatus.rejected,
}


def build_search_url(keyword: str, city: str) -> str:
    """求职意向 → 检索参数（禁止全量抓取）。"""
    city_code = CITY_CODE_MAP.get(city, "101010100")
    from urllib.parse import quote

    return SEARCH_URL_TEMPLATE.format(keyword=quote(keyword or "开发"), city_code=city_code)


def receipt_ref(position_id: str) -> str:
    """回执引用：职位加密 ID 或沟通标识。"""
    return f"boss:{position_id}"