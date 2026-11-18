"""平台浏览器工作线程：单平台专属守护线程串行消费命令队列。

合规红线（不可违反）：
- headed 有头模式；channel=msedge 探测失败自动 chrome；不注入自定义 UA/指纹脚本；不配置任何代理。
- 命令 deadline：拉取 600s / 投递 180s / 授权校验 60s / 状态查询 300s，超时明确失败。
- 命令间 2-5s 随机节流。
- 浏览器崩溃/会话中断时当前命令抛 PlatformUnavailableError 并释放资源，禁止半完成误判为成功。
"""

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config import settings
from app.infra.logging import get_logger

logger = get_logger("browser_worker")

FETCH_DEADLINE_SECONDS = 600
SUBMIT_DEADLINE_SECONDS = 180
VALIDATE_DEADLINE_SECONDS = 60
STATUS_DEADLINE_SECONDS = 300


class OpType(str, Enum):
    FETCH = "fetch"
    SUBMIT = "submit"
    VALIDATE = "validate"
    STATUS = "status"
    AUTH_FLOW = "auth_flow"
    FETCH_JD = "fetch_jd"


FETCH_JD_DEADLINE_SECONDS = 60


class SessionState(str, Enum):
    CLOSED = "closed"
    STARTING = "starting"
    READY = "ready"
    EXECUTING = "executing"
    WAITING_CAPTCHA = "waiting_captcha"
    FAILED = "failed"


@dataclass
class BrowserCommand:
    """队列命令：操作类型/入参/deadline/结果回填槽。"""

    op_type: OpType
    payload: dict = field(default_factory=dict)
    deadline_seconds: int = FETCH_DEADLINE_SECONDS
    command_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    done_event: threading.Event = field(default_factory=threading.Event, repr=False)
    result: object | None = None
    error: Exception | None = None

    def deadline_deadline(self) -> float:
        base = {
            OpType.FETCH: FETCH_DEADLINE_SECONDS,
            OpType.SUBMIT: SUBMIT_DEADLINE_SECONDS,
            OpType.VALIDATE: VALIDATE_DEADLINE_SECONDS,
            OpType.STATUS: STATUS_DEADLINE_SECONDS,
            OpType.FETCH_JD: FETCH_JD_DEADLINE_SECONDS,
        }
        return base.get(self.op_type, FETCH_DEADLINE_SECONDS)


class CommandTimeoutError(Exception):
    """命令超过 deadline：明确失败，禁止无限等待。"""


class PlatformBrowserWorker:
    """单平台专属工作线程：命令串行执行，事件循环零阻塞。

    页面操作逻辑由注入的 executor 承载（executor(page, command) -> result），
    worker 只负责线程模型/会话状态机/超时/节流/资源释放。
    """

    def __init__(self, platform_id: str) -> None:
        self.platform_id = platform_id
        self._queue: queue.Queue[BrowserCommand] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = SessionState.CLOSED
        self._browser = None
        self._context = None
        self._page = None
        self._last_active = time.monotonic()
        self._lock = threading.Lock()
        self._executor = None
        self._session_factory = None

    # ---- 生命周期 ----

    def bind_executor(self, executor, session_factory) -> None:
        """executor(page, command)->result：页面操作承载逻辑（适配器注入）。"""
        self._executor = executor
        self._session_factory = session_factory

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"browser-worker-{self.platform_id}", daemon=True
        )
        self._thread.start()

    def stop(self, close_browser: bool = True) -> None:
        self._stop.set()
        if close_browser:
            self._close_browser_locked()
        if self._thread:
            self._thread.join(timeout=5)

    # ---- 命令提交 ----

    def submit(self, command: BrowserCommand) -> object:
        """阻塞等待命令结果（调用方已在 to_thread 线程，不阻塞事件循环）。"""
        self._queue.put(command)
        remaining = command.deadline_deadline()
        if not command.done_event.wait(timeout=remaining + 5):
            raise CommandTimeoutError(
                f"平台 {self.platform_id} 命令 {command.op_type.value} 超时（{remaining}s）"
            )
        if command.error is not None:
            raise command.error
        return command.result

    # ---- 线程主循环 ----

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                command = self._queue.get(timeout=1)
            except queue.Empty:
                self._idle_recycle_check()
                continue
            self._execute(command)
            self._throttle()

    def _execute(self, command: BrowserCommand) -> None:
        logger.info(
            "browser_command_start",
            platform_id=self.platform_id,
            op=command.op_type.value,
            command_id=command.command_id,
        )
        try:
            page = self._ensure_session(command)
            self.state = SessionState.EXECUTING
            result = self._executor(page, command)
            command.result = result
            command.error = None
            self.state = SessionState.READY
            self._last_active = time.monotonic()
            logger.info(
                "browser_command_done",
                platform_id=self.platform_id,
                op=command.op_type.value,
                command_id=command.command_id,
            )
        except Exception as exc:  # noqa: BLE001
            command.error = exc
            command.result = None
            self.state = SessionState.FAILED
            self._last_active = time.monotonic()
            logger.warning(
                "browser_command_failed",
                platform_id=self.platform_id,
                op=command.op_type.value,
                command_id=command.command_id,
                reason=str(exc),
            )
            if self._is_session_broken(exc):
                self._close_browser_locked()
        finally:
            command.done_event.set()

    def _ensure_session(self, command: BrowserCommand):
        """确保受控浏览器会话可用（会话状态机 Closed/Starting/Ready 迁移）。"""
        if self._page is not None:
            return self._page
        self.state = SessionState.STARTING
        from playwright.sync_api import sync_playwright

        from app.real_platform.browser import state_store

        channel = self._pick_channel()
        self._pw = sync_playwright().start()
        launch_kwargs = {"headless": False, "channel": channel}
        profile = state_store.profile_dir(self.platform_id)
        storage_state = command.payload.get("storage_state")
        if state_store.has_persistent_profile(self.platform_id):
            profile.mkdir(parents=True, exist_ok=True)
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile), **launch_kwargs
            )
        elif storage_state is not None:

            browser = self._pw.chromium.launch(**launch_kwargs)
            self._browser = browser
            self._context = browser.new_context(storage_state=storage_state)
        else:
            browser = self._pw.chromium.launch(**launch_kwargs)
            self._browser = browser
            self._context = browser.new_context()
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.state = SessionState.READY
        return self._page

    def _pick_channel(self) -> str:
        """按配置通道序探测本机浏览器（msedge 优先，chrome 兜底）。"""
        for channel in settings.browser_channel_order:
            try:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as probe:
                    probe.chromium.launch(headless=False, channel=channel).close()
                return channel
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("本机未探测到可用浏览器（Chrome/Edge）")

    def _is_session_broken(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(k in text for k in ("target closed", "browser closed", "connection closed", "操作环境异常"))

    def _close_browser_locked(self) -> None:
        with self._lock:
            for resource_name in ("_context", "_browser", "_pw"):
                resource = getattr(self, resource_name, None)
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:  # noqa: BLE001
                        pass
                    setattr(self, resource_name, None)
            self._page = None
            self.state = SessionState.CLOSED

    def _idle_recycle_check(self) -> None:
        """空闲回收：仅关闭浏览器进程，worker 线程保留。"""
        if self._page is None:
            return
        idle = time.monotonic() - self._last_active
        if idle > settings.browser_idle_recycle_seconds:
            logger.info("browser_idle_recycled", platform_id=self.platform_id, idle_seconds=round(idle))
            self._close_browser_locked()

    def _throttle(self) -> None:
        low, high = settings.browser_command_throttle_seconds
        time.sleep(_throttle_random(low, high))


def _throttle_random(low: int, high: int) -> float:
    import random

    return random.uniform(low, high)