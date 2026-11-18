"""AI 用户级设置 KV 键辅助（复用既有 SettingRepository）。

8 个键：ai_enabled / ai_mask_enabled / ai_mask_fields / ai_jd_truncate_limit /
ai_resume_truncate_limit / ai_greeting_max_len / ai_greeting_tone / ai_send_full_resume。
未写入任何键时读取全部返回默认值（开箱即用不受影响）。
"""

from sqlalchemy.orm import Session

from app.repositories.repos import SettingRepository

AI_KEYS_DEFAULTS = {
    "ai_enabled": True,
    "ai_mask_enabled": True,
    "ai_mask_fields": ["phone", "email"],
    "ai_jd_truncate_limit": 2000,
    "ai_resume_truncate_limit": 3000,
    "ai_greeting_max_len": 200,
    "ai_greeting_tone": "professional",
    "ai_send_full_resume": False,
}

_SETTING_KEYS = {k: v for k, v in AI_KEYS_DEFAULTS.items()}


class AiSettings:
    def __init__(self, session: Session) -> None:
        self._repo = SettingRepository(session)

    def get_all(self) -> dict:
        result = {}
        for key, default in _SETTING_KEYS.items():
            value = self._repo.get(key, default)
            if isinstance(default, list) and not isinstance(value, list):
                value = default
            result[key] = value
        return result

    def get(self, key: str):
        if key not in _SETTING_KEYS:
            raise KeyError(f"未知 AI 设置键: {key}")
        return self._repo.get(key, _SETTING_KEYS[key])

    def set(self, key: str, value) -> None:
        if key not in _SETTING_KEYS:
            raise KeyError(f"未知 AI 设置键: {key}")
        self._repo.set(key, value)

    @property
    def enabled(self) -> bool:
        return bool(self._repo.get("ai_enabled", True))

    @property
    def mask_enabled(self) -> bool:
        return bool(self._repo.get("ai_mask_enabled", True))

    @property
    def mask_fields(self) -> list[str]:
        value = self._repo.get("ai_mask_fields", ["phone", "email"])
        return value if isinstance(value, list) else ["phone", "email"]

    @property
    def jd_truncate_limit(self) -> int:
        return int(self._repo.get("ai_jd_truncate_limit", 2000))

    @property
    def resume_truncate_limit(self) -> int:
        return int(self._repo.get("ai_resume_truncate_limit", 3000))

    @property
    def greeting_max_len(self) -> int:
        return int(self._repo.get("ai_greeting_max_len", 200))

    @property
    def greeting_tone(self) -> str:
        return str(self._repo.get("ai_greeting_tone", "professional"))

    @property
    def send_full_resume(self) -> bool:
        return bool(self._repo.get("ai_send_full_resume", False))