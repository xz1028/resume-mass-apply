"""BOSS直聘适配器：沟通制投递链路（立即沟通→聊天发送招呼=投递完成）。

EncryptedResumeRef 仅用于日志记录不发送（沟通制无附件动作）。
"""

from app.real_platform.adapters.base import RealPlatformAdapterBase
from app.real_platform.pages import boss as pages


class BossZhipinAdapter(RealPlatformAdapterBase):
    def __init__(self, rate_per_hour: float = 20.0) -> None:
        super().__init__(pages, rate_per_hour)

    def _apply_flow_name(self) -> str:
        return "boss_chat"

    def _status_page_url(self) -> str:
        return pages.MY_MESSAGE_URL

    def _probe_url(self) -> str:
        return pages.MY_MESSAGE_URL