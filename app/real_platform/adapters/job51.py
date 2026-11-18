"""前程无忧适配器：申请弹窗确认链路（申请职位→确认弹窗→提交）。"""

from app.real_platform.adapters.base import RealPlatformAdapterBase
from app.real_platform.pages import job51 as pages


class Job51Adapter(RealPlatformAdapterBase):
    def __init__(self, rate_per_hour: float = 20.0) -> None:
        super().__init__(pages, rate_per_hour)

    def _apply_flow_name(self) -> str:
        return "job51_apply"

    def _status_page_url(self) -> str:
        return pages.MY_APPLICATION_URL

    def _probe_url(self) -> str:
        return pages.MY_APPLICATION_URL