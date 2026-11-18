"""登录态持久化与恢复：双通道（用户数据目录 / storage_state 凭证重建）。

凭证为 cookies+localStorage 的 JSON 序列化串（不含任何账密字段），
经既有 CryptoService 解密后使用。
"""

import json
from pathlib import Path

from app.config import settings
from app.infra.logging import get_logger
from app.platforms.spi import PlatformAuthExpiredError

logger = get_logger("state_store")


def profile_dir(platform_id: str) -> Path:
    return settings.browser_profiles_dir / platform_id


def storage_state_to_credential(state: dict) -> str:
    """storage_state 字典 → 凭证字符串（JSON 序列化，无账密字段）。"""
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def credential_to_storage_state(credential: str) -> dict:
    """凭证字符串 → storage_state 字典；解析失败视为登录态失效。"""
    try:
        state = json.loads(credential)
    except (ValueError, TypeError) as exc:
        raise PlatformAuthExpiredError("登录态凭证解析失败，请重新授权") from exc
    if not isinstance(state, dict) or "cookies" not in state:
        raise PlatformAuthExpiredError("登录态凭证结构无效，请重新授权")
    return state


def has_persistent_profile(platform_id: str) -> bool:
    """用户数据目录是否存在且含浏览器 profile 标记文件。"""
    marker = profile_dir(platform_id) / "Default"
    return marker.is_dir()


def clear_profile(platform_id: str) -> None:
    """撤销/禁用时清理用户数据目录（撤销兜底）。"""
    import shutil

    path = profile_dir(platform_id)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        logger.info("browser_profile_cleared", platform_id=platform_id)