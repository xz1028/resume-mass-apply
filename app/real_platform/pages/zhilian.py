"""智联招聘页面对象常量：URL 模式、多候选选择器、状态映射、检索参数映射。"""

from app.domain.models import DeliveryStatus

PLATFORM_ID = "zhilian"
PLATFORM_NAME = "智联招聘"

LOGIN_URL = "https://passport.zhaopin.com/v5/login"
SEARCH_URL_TEMPLATE = "https://sou.zhaopin.com/?jl={city_code}&kw={keyword}"
MY_APPLICATION_URL = "https://i.zhaopin.com/api/deliver/position?deliverState=0"

CITY_CODE_MAP = {
    "北京": "530", "上海": "538", "深圳": "765", "广州": "763",
    "杭州": "653", "成都": "801", "武汉": "736", "南京": "639",
    "西安": "854", "长沙": "749", "苏州": "636", "东莞": "858",
    "佛山": "860", "重庆": "551", "郑州": "680", "宁波": "654",
    "厦门": "682", "青岛": "702", "天津": "564", "济南": "613",
    "合肥": "651", "福州": "681", "珠海": "858",
}

LOGIN_STATE_SELECTORS = [
    ".zp-user-info",
    "a[href*='i.zhaopin.com']",
    ".user-name",
    "[class*='userInfo']",
]

RESULT_CONTAINER_SELECTORS = [".positionlist", ".joblist-box", "[class*='sou-job-list']"]
CARD_SELECTORS = [".joblist-box__item", ".positionlist-item", ".job-item"]
CARD_TITLE_SELECTORS = [".jobinfo__name", ".positionName", ".job-name"]
CARD_COMPANY_SELECTORS = [".companyinfo__name", ".companyName", ".company-name"]
CARD_SALARY_SELECTORS = [".jobinfo__salary", ".salary", ".job-salary"]
CARD_CITY_SELECTORS = [".jobinfo__city", ".job-area", ".work-city"]
CARD_LINK_SELECTORS = ["a.jobinfo__name", ".job-item a", "a[class*='positionName']"]

DETAIL_CONTAINER_SELECTORS = [".job-detail-box", ".position-detail", ".job-intro"]
DETAIL_PUBLISH_TIME_SELECTORS = [".job-update-time", ".publish-time"]

# 申请链路：申请按钮 → 简历选择（附件优先）→ 提交确认
APPLY_BUTTON_SELECTORS = [".apply-btn", "a[ka='job_apply']", ".btn-apply"]
RESUME_UPLOAD_SELECTORS = ["input[type='file']", ".upload-btn input"]
RESUME_SELECT_SELECTORS = [".resume-item", ".resume-select"]
APPLY_CONFIRM_SELECTORS = [".dialog-confirm", ".btn-submit", ".confirm-btn"]

ALREADY_APPLIED_SELECTORS = [".apply-btn.disabled", ".applied-tag"]
ALREADY_APPLIED_TEXTS = ["已申请", "已投递", "申请成功"]

CAPTCHA_URL_HINTS = ["verify", "captcha", "validate"]
CAPTCHA_CONTAINER_SELECTORS = [".captcha-panel", "#captcha", ".verify-code-box"]

LOGIN_URL_MARKS = ["login", "passport"]

STATUS_LABEL_MAP = {
    "已查看": DeliveryStatus.viewed,
    "人事已查看": DeliveryStatus.viewed,
    "面试邀请": DeliveryStatus.interview_invited,
    "邀请面试": DeliveryStatus.interview_invited,
    "不合适": DeliveryStatus.rejected,
    "未通过": DeliveryStatus.rejected,
}


def build_search_url(keyword: str, city: str) -> str:
    from urllib.parse import quote

    city_code = CITY_CODE_MAP.get(city, "530")
    return SEARCH_URL_TEMPLATE.format(city_code=city_code, keyword=quote(keyword or "开发"))


def receipt_ref(position_id: str) -> str:
    """回执引用：职位编号。"""
    return f"zhilian:{position_id}"