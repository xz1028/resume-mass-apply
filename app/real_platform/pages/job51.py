"""前程无忧页面对象常量：URL 模式、多候选选择器、状态映射、检索参数映射。"""

from app.domain.models import DeliveryStatus

PLATFORM_ID = "job51"
PLATFORM_NAME = "前程无忧"

LOGIN_URL = "https://login.51job.com/login.php"
SEARCH_URL_TEMPLATE = "https://we.51job.com/pc/search?searchType=advance&jobArea={area_code}&keyword={keyword}"
MY_APPLICATION_URL = "https://my.51job.com/my/apply.php"

AREA_CODE_MAP = {
    "北京": "010000", "上海": "020000", "深圳": "040000", "广州": "030200",
    "杭州": "080200", "成都": "090200", "武汉": "170200", "南京": "070200",
    "西安": "200200", "长沙": "190200", "苏州": "060400", "东莞": "030800",
    "佛山": "030600", "重庆": "060000", "郑州": "170500", "宁波": "080400",
    "厦门": "110300", "青岛": "120300", "天津": "050000", "济南": "120200",
    "合肥": "150200", "福州": "110100", "珠海": "030500",
}

LOGIN_STATE_SELECTORS = [
    ".user-name",
    "a[href*='my.51job.com']",
    ".jname",
    "[class*='username']",
]

RESULT_CONTAINER_SELECTORS = [".j_jobList", ".joblist", "[class*='search-result']"]
CARD_SELECTORS = [".joblist-item", ".e", ".job-item"]
CARD_TITLE_SELECTORS = [".jobname a", ".t", ".job-title a"]
CARD_COMPANY_SELECTORS = [".cname a", ".company-name", ".job_cmp"]
CARD_SALARY_SELECTORS = [".money", ".salary", ".job_salary"]
CARD_CITY_SELECTORS = [".info span", ".job-area", ".workplace"]
CARD_LINK_SELECTORS = [".jobname a", "a.t", ".job-title a"]

DETAIL_CONTAINER_SELECTORS = [".job_detail", ".cn_detail", ".job-intro"]
DETAIL_PUBLISH_TIME_SELECTORS = [".time", ".publish-time"]

# 申请链路：申请按钮 → 确认弹窗 → 提交
APPLY_BUTTON_SELECTORS = [".job_apply", "a[ka='job_apply']", ".btn-apply"]
APPLY_CONFIRM_DIALOG_SELECTORS = [".dialog-body", ".confirm-dialog", "#apply-confirm"]
APPLY_CONFIRM_BUTTON_SELECTORS = [".dialog-ok", ".btn-confirm", ".p_btn"]

ALREADY_APPLIED_SELECTORS = [".job_apply.disabled", ".applied"]
ALREADY_APPLIED_TEXTS = ["已申请", "已投递", "申请成功", "已发送"]

CAPTCHA_URL_HINTS = ["verify", "captcha", "checkcode"]
CAPTCHA_CONTAINER_SELECTORS = [".captcha-img", "#checkcode", ".verify-panel"]

LOGIN_URL_MARKS = ["login", "signin"]

STATUS_LABEL_MAP = {
    "人事已查看": DeliveryStatus.viewed,
    "已查看": DeliveryStatus.viewed,
    "面试邀请": DeliveryStatus.interview_invited,
    "邀约": DeliveryStatus.interview_invited,
    "不合适": DeliveryStatus.rejected,
    "不适合": DeliveryStatus.rejected,
}


def build_search_url(keyword: str, city: str) -> str:
    from urllib.parse import quote

    area_code = AREA_CODE_MAP.get(city, "010000")
    return SEARCH_URL_TEMPLATE.format(area_code=area_code, keyword=quote(keyword or "开发"))


def receipt_ref(position_id: str) -> str:
    """回执引用：职位 ID。"""
    return f"job51:{position_id}"