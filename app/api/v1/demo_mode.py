"""演示模式 REST API（tasks 2.5）：状态查询 + 一键清除（幂等空操作不报错）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.services.demo_mode_service import DemoModeService

router = APIRouter(prefix="/api/v1/demo-mode", tags=["demo-mode"])


@router.get("")
def get_demo_mode_status(session: Session = Depends(get_session)) -> dict:
    """演示模式状态：active / state / clearable_summary（resumes/records/positions）。"""
    return DemoModeService(session).status()


@router.post("/reset")
def reset_demo_mode(session: Session = Depends(get_session)) -> dict:
    """退出演示模式：四键圈定清除（演示简历/任务与记录/跨平台职位/标记）。

    非演示态为幂等空操作，返回全 0 计数不报错（spec 5.2.1.7）。
    """
    return DemoModeService(session).reset()