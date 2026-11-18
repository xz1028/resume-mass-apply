"""智联招聘适配器：申请确认链路（申请该职位→简历选择/附件上传→提交）。"""

from app.real_platform.adapters.base import RealPlatformAdapterBase
from app.real_platform.pages import zhilian as pages


class ZhilianAdapter(RealPlatformAdapterBase):
    def __init__(self, rate_per_hour: float = 20.0) -> None:
        super().__init__(pages, rate_per_hour)

    def _apply_flow_name(self) -> str:
        return "zhilian_apply"

    def _status_page_url(self) -> str:
        return pages.MY_APPLICATION_URL

    def _probe_url(self) -> str:
        return pages.MY_APPLICATION_URL