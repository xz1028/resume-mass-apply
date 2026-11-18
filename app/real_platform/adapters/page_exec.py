"""页面对接执行器：命令 → Playwright 页面操作（三平台共用骨架，差异由 pages 配置隔离）。

执行链路含：验证码特征检测（转人工门闸）、风控信号检测、登录态恢复、
结果解析、幂等复核。页面结构变更时仅改 pages 配置与本模块映射。
"""

import asyncio  # noqa: F401
from datetime import datetime

from app.domain.models import ContactInfo, DeliveryStatus, JobIntention
from app.infra.logging import get_logger
from app.platforms.spi import (
    ApplyResult,
    PlatformAuthExpiredError,
    PlatformRateLimitedError,
    PlatformUnavailableError,
    PositionDTO,
    StatusReceipt,
)
from app.real_platform.browser import risk as risk_detector
from app.real_platform.browser.selectors import SelectorGroup, try_locate

logger = get_logger("page_exec")

PUBLISH_DAYS_DEFAULT = 30


def execute(adapter, page, command):
    """命令路由：fetch/submit/status/validate/auth_flow/fetch_jd。"""
    op = command.op_type.value
    if op == "fetch":
        return _execute_fetch(adapter, page, command)
    if op == "submit":
        return _execute_submit(adapter, page, command)
    if op == "status":
        return _execute_status(adapter, page, command)
    if op == "validate":
        return _execute_validate(adapter, page, command)
    if op == "auth_flow":
        return _execute_auth_flow(adapter, page, command)
    if op == "fetch_jd":
        return _execute_fetch_jd(adapter, page, command)
    raise PlatformUnavailableError(f"未知命令类型: {op}")


# ---------- 通用工具 ----------

def _first(page, group: SelectorGroup):
    """多候选选择器依次尝试，返回首个命中元素或 None（失败记录 parse_stage）。"""

    def attempt(selector: str):
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                return locator.first
            return None
        except Exception:  # noqa: BLE001
            return None

    report = try_locate(group, attempt)
    if not report.ok and group.parse_stage:
        # 关键定位组失败 → 页面结构变更特征
        risk_detector.raise_for_parse_failure(adapter.platform_id, adapter._session_factory(), report.parse_stage)
    return None if not report.ok else page.locator(group.candidates[report.success_index]).first


def _text(el) -> str:
    try:
        return (el.inner_text() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _check_page_signals(adapter, page) -> None:
    """页面级信号：验证码特征 → 门闸；风控文案 → 异常归类；登录页重定向 → 授权过期。"""
    pages = adapter.pages
    url = page.url.lower()
    if any(hint in url for hint in pages.CAPTCHA_URL_HINTS):
        from app.real_platform.browser import captcha as captcha_gate

        captcha_gate.open_challenge(adapter._session_factory(), adapter.platform_id, "navigation")
        raise PlatformRateLimitedError(f"平台 {adapter.platform_id} 需人机验证，已转人工处理")
    body = ""
    try:
        body = page.locator("body").inner_text()[:2000]
    except Exception:  # noqa: BLE001
        pass
    login_hint = any(mark in url for mark in pages.LOGIN_URL_MARKS)
    risk_detector.raise_for_page_text(body, adapter.platform_id, adapter._session_factory(), login_url_hint=login_hint)


def _ensure_login(adapter, page) -> None:
    """登录态检查：登录态特征元素缺失 → 授权过期。"""
    group = SelectorGroup(
        name="login_state",
        candidates=adapter.pages.LOGIN_STATE_SELECTORS,
        parse_stage="login_state_missing",
    )

    def attempt(selector: str):
        try:
            locator = page.locator(selector)
            return locator if locator.count() > 0 else None
        except Exception:  # noqa: BLE001
            return None

    report = try_locate(group, attempt)
    if not report.ok:
        raise PlatformAuthExpiredError(
            f"平台 {adapter.platform_id} 登录态已失效，请重新授权"
        )


# ---------- 拉取 ----------

def _execute_fetch(adapter, page, command):
    pages = adapter.pages
    intent: JobIntention = command.payload["intent"]
    page.goto(command.payload["search_url"], timeout=45000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _check_page_signals(adapter, page)
    _ensure_login(adapter, page)

    container = _first(page, SelectorGroup("result_container", pages.RESULT_CONTAINER_SELECTORS, parse_stage="result_container"))
    if container is None:
        return []

    cards = []
    for selector in pages.CARD_SELECTORS:
        try:
            found = container.locator(selector)
            if found.count() > 0:
                cards = list(found.all())
                break
        except Exception:  # noqa: BLE001
            continue
    positions: list[dict] = []
    expire = adapter.derive_expire(PUBLISH_DAYS_DEFAULT)
    for card in cards[:50]:
        try:
            title_el = card.locator(pages.CARD_TITLE_SELECTORS[0]).first
            title = _text(title_el)
            company = _text(card.locator(pages.CARD_COMPANY_SELECTORS[0]).first)
            salary_text = _text(card.locator(pages.CARD_SALARY_SELECTORS[0]).first)
            city_text = _text(card.locator(pages.CARD_CITY_SELECTORS[0]).first)
            link_el = card.locator(pages.CARD_LINK_SELECTORS[0]).first
            href = link_el.get_attribute("href") or ""
            position_id = href.strip("/").split("/")[-1].split("?")[0] if href else ""
            smin, smax = _parse_salary(salary_text)
            positions.append(
                {
                    "position_id": position_id,
                    "platform_id": adapter.platform_id,
                    "title": title,
                    "company": company,
                    "city": city_text.split("·")[0] if city_text else "",
                    "salary_min": smin,
                    "salary_max": smax,
                    "industry": intent.industry or "",
                    "experience_req": "",
                    "publish_expire_at": expire,
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("card_parse_skip", platform_id=adapter.platform_id)
            continue
    return positions


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    import re

    if not text:
        return None, None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-kK]\s*(\d+(?:\.\d+)?)", text)
    if m:
        return int(float(m.group(1)) * 1000), int(float(m.group(2)) * 1000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[kK]", text)
    if m:
        v = int(float(m.group(1)) * 1000)
        return v, None
    return None, None


# ---------- 投递 ----------

def _execute_submit(adapter, page, command):
    pages = adapter.pages
    position: PositionDTO = command.payload["position"]
    resume_file = command.payload["resume_file"]
    contact: ContactInfo = command.payload["contact"]

    detail_url = getattr(pages, "DETAIL_URL_PATTERN", "") and _detail_url(adapter, position)
    page.goto(detail_url, timeout=45000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _check_page_signals(adapter, page)
    _ensure_login(adapter, page)

    # 幂等复核：已投递信号 → 返回成功带既有引用（禁止重复投递）
    for selector in pages.ALREADY_APPLIED_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return ApplyResult(
                    success=True,
                    platform_record_ref=pages.receipt_ref(position.position_id),
                    failure_reason=None,
                    receipt_time=datetime.now(),
                )
        except Exception:  # noqa: BLE001
            continue
    body_text = ""
    try:
        body_text = page.locator("body").inner_text()[:1000]
    except Exception:  # noqa: BLE001
        pass
    if any(mark in body_text for mark in pages.ALREADY_APPLIED_TEXTS):
        return ApplyResult(
            success=True,
            platform_record_ref=pages.receipt_ref(position.position_id),
            failure_reason=None,
            receipt_time=datetime.now(),
        )

    # 投递前置复核：职位在招状态（已关闭 → success=False 不重试）
    if _position_closed(page, body_text):
        return ApplyResult(
            success=False,
            platform_record_ref=None,
            failure_reason="职位已关闭",
            receipt_time=datetime.now(),
        )

    # 平台差异链路
    flow = command.payload.get("apply_flow", "")
    if flow == "boss_chat":
        return _apply_boss_chat(adapter, page, position, command.payload.get("greeting"))
    if flow == "zhilian_apply":
        return _apply_zhilian(adapter, page, position, resume_file)
    return _apply_job51(adapter, page, position)


def _detail_url(adapter, position: PositionDTO) -> str:
    pages = adapter.pages
    if hasattr(pages, "DETAIL_URL_PATTERN"):
        return pages.DETAIL_URL_PATTERN + position.position_id + ".html"
    raise PlatformUnavailableError("详情页 URL 模式缺失")


def _position_closed(page, body_text: str) -> bool:
    closed_marks = ("职位已关闭", "已停止招聘", "职位已下线", "该职位已失效")
    return any(mark in body_text for mark in closed_marks)


def _apply_boss_chat(adapter, page, position, greeting: str | None):
    pages = adapter.pages
    chat_btn = _first(page, SelectorGroup("chat_btn", pages.CHAT_BUTTON_SELECTORS))
    if chat_btn is None:
        raise PlatformUnavailableError("沟通按钮定位失败，页面结构可能已变更")
    chat_btn.click()
    page.wait_for_timeout(2000)
    _check_page_signals(adapter, page)
    greeting = greeting or (
        f"您好，我对贵公司「{position.title}」职位很感兴趣，"
        "具备相应技能与经验，期待进一步沟通，我的简历已随消息附上，感谢查阅！"
    )
    for selector in pages.GREETING_SEND_SELECTORS:
        try:
            box = page.locator(selector)
            if box.count() > 0:
                box.first.fill(greeting)
                break
        except Exception:  # noqa: BLE001
            continue
    for selector in pages.GREETING_SEND_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector)
            if btn.count() > 0:
                btn.first.click()
                break
        except Exception:  # noqa: BLE001
            continue
    page.wait_for_timeout(1500)
    return ApplyResult(
        success=True,
        platform_record_ref=pages.receipt_ref(position.position_id),
        receipt_time=datetime.now(),
    )


def _apply_zhilian(adapter, page, position, resume_file):
    pages = adapter.pages
    apply_btn = _first(page, SelectorGroup("apply_btn", pages.APPLY_BUTTON_SELECTORS))
    if apply_btn is None:
        raise PlatformUnavailableError("申请按钮定位失败，页面结构可能已变更")
    apply_btn.click()
    page.wait_for_timeout(1500)
    # 附件简历真实上传（EncryptedResumeRef.content 经平台上传控件发送）
    for selector in pages.RESUME_UPLOAD_SELECTORS:
        try:
            upload = page.locator(selector)
            if upload.count() > 0:
                upload.first.set_input_files(
                    {"name": f"resume.{resume_file.format}", "mimeType": "application/pdf", "buffer": resume_file.content}
                )
                break
        except Exception:  # noqa: BLE001
            continue
    for selector in pages.APPLY_CONFIRM_SELECTORS:
        try:
            confirm = page.locator(selector)
            if confirm.count() > 0 and confirm.first.is_enabled():
                confirm.first.click()
                break
        except Exception:  # noqa: BLE001
            continue
    page.wait_for_timeout(2000)
    return ApplyResult(
        success=True,
        platform_record_ref=pages.receipt_ref(position.position_id),
        receipt_time=datetime.now(),
    )


def _apply_job51(adapter, page, position):
    pages = adapter.pages
    apply_btn = _first(page, SelectorGroup("apply_btn", pages.APPLY_BUTTON_SELECTORS))
    if apply_btn is None:
        raise PlatformUnavailableError("申请按钮定位失败，页面结构可能已变更")
    apply_btn.click()
    page.wait_for_timeout(1500)
    for dialog_sel in pages.APPLY_CONFIRM_DIALOG_SELECTORS:
        try:
            dialog = page.locator(dialog_sel)
            if dialog.count() > 0:
                for btn_sel in pages.APPLY_CONFIRM_BUTTON_SELECTORS:
                    btn = dialog.locator(btn_sel)
                    if btn.count() > 0:
                        btn.first.click()
                        break
                break
        except Exception:  # noqa: BLE001
            continue
    page.wait_for_timeout(2000)
    return ApplyResult(
        success=True,
        platform_record_ref=pages.receipt_ref(position.position_id),
        receipt_time=datetime.now(),
    )


# ---------- 状态查询 ----------

def _execute_status(adapter, page, command):
    pages = adapter.pages
    record_refs = command.payload["record_refs"]
    status_map = command.payload["status_map"]
    page.goto(command.payload["status_url"], timeout=45000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _check_page_signals(adapter, page)
    _ensure_login(adapter, page)

    body_text = ""
    try:
        body_text = page.locator("body").inner_text()[:5000]
    except Exception:  # noqa: BLE001
        pass
    receipts = []
    seq = 0
    now = datetime.now()
    for ref in record_refs:
        raw_id = ref.platform_record_ref.split(":", 1)[-1] if ":" in ref.platform_record_ref else ref.platform_record_ref
        new_status = _match_status(body_text, raw_id, status_map)
        if new_status is not None:
            seq += 1
            receipts.append(
                StatusReceipt(
                    record_ref=ref.platform_record_ref,
                    new_status=new_status,
                    receipt_time=now,
                    receipt_seq=seq,
                )
            )
    return receipts


def _match_status(body_text: str, raw_id: str, status_map: dict) -> DeliveryStatus | None:
    window = body_text
    if raw_id and raw_id in window:
        idx = window.find(raw_id)
        window = window[max(0, idx - 100) : idx + 300]
    for label, status in status_map.items():
        if label in window:
            return status
    return None


# ---------- 授权校验 ----------

def _execute_validate(adapter, page, command):
    pages = adapter.pages
    page.goto(command.payload["probe_url"], timeout=45000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _check_page_signals(adapter, page)

    group = SelectorGroup("login_state", pages.LOGIN_STATE_SELECTORS)
    report = try_locate(
        group,
        lambda sel: page.locator(sel) if page.locator(sel).count() > 0 else None,
    )
    return "authorized" if report.ok else "unauthorized"


# ---------- 授权会话 ----------

def _execute_auth_flow(adapter, page, command):
    pages = adapter.pages
    session = command.payload.get("auth_session")
    page.goto(pages.LOGIN_URL, timeout=45000)
    page.wait_for_timeout(1000)

    # 等待用户在浏览器窗口完成登录（仅依赖登录态特征元素，不读表单）
    deadline = command.deadline_deadline() or 300
    import time as _time

    start = _time.monotonic()
    while _time.monotonic() - start < min(deadline, 480):
        if session and session.status == "cancelled":
            return None
        try:
            if page.locator(pages.LOGIN_STATE_SELECTORS[0]).count() > 0:
                break
            url = page.url.lower()
            if any(hint in url for hint in pages.CAPTCHA_URL_HINTS):
                if session:
                    session.mark("captcha_pending")
                page.wait_for_timeout(3000)
                continue
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(LOGIN_POLL_INTERVAL * 1000)
    else:
        raise PlatformAuthExpiredError("登录等待超时，请重新发起授权")

    if session:
        session.mark("waiting_login") if session.status == "browser_opening" else None
    state = page.context.storage_state()
    from app.real_platform.browser.state_store import storage_state_to_credential

    return storage_state_to_credential(state)


LOGIN_POLL_INTERVAL = 2

# ---------- JD 文本抓取（AI 匹配消费） ----------

def _execute_fetch_jd(adapter, page, command):
    """访问职位详情页提取职位描述正文；失败抛平台异常（由 fetcher 走降级拼接）。"""
    pages = adapter.pages
    position = command.payload.get("position")
    if position is None:
        raise PlatformUnavailableError("fetch_jd 命令缺少职位参数")
    detail_url = _detail_url(adapter, position)
    page.goto(detail_url, timeout=45000)
    page.wait_for_load_state("networkidle", timeout=30000)
    _check_page_signals(adapter, page)
    _ensure_login(adapter, page)

    container = _first(
        page,
        SelectorGroup("detail_container", pages.DETAIL_CONTAINER_SELECTORS, parse_stage="detail_container"),
    )
    if container is None:
        raise PlatformUnavailableError("职位详情容器定位失败，页面结构可能已变更")
    try:
        jd_text = (container.inner_text() or "").strip()
    except Exception as exc:  # noqa: BLE001
        raise PlatformUnavailableError(f"职位描述提取失败: {exc}") from exc
    if not jd_text:
        raise PlatformUnavailableError("职位描述为空，页面结构可能已变更")
    return jd_text