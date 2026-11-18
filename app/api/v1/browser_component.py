"""浏览器组件状态查询 API（tasks 2.6，design 决策 D5）。

核心绿色包不含 playwright；启用真实平台前前端查询本接口，
组件缺失以 available=false 正常返回（非错误响应）+ 获取指引文案。
探测无导入副作用（try/except import）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/platform-access", tags=["browser-component"])

GUIDE_TEXT = (
    "浏览器自动化组件未随核心包分发（控制体积）。"
    "如需启用真实平台投递：安装 Python 3.11 后执行 pip install playwright，"
    "或参考分发包 RELEASE_NOTES 中的组件获取指引；"
    "模拟招聘平台的演示旅程不受影响。"
)


@router.get("/browser-component")
def browser_component_status() -> dict:
    try:
        import playwright.sync_api  # noqa: F401

        available = True
        reason = ""
    except ImportError:
        available = False
        reason = "未安装 playwright 组件"
    return {
        "available": available,
        "reason": reason,
        "guide": "" if available else GUIDE_TEXT,
    }