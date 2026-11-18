"""加密服务：AES-256-GCM 认证加密，用于简历文件与平台授权凭证。

密钥由本地密钥文件管理：不存在时自动生成，存在时加载。
篡改密文后解密抛出完整性错误（cryptography.exceptions.InvalidTag）。
"""

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12


class CryptoService:
    def __init__(self, key_file: Path) -> None:
        self._key_file = key_file
        self._key = self._load_or_create_key()
        self._aesgcm = AESGCM(self._key)

    def _load_or_create_key(self) -> bytes:
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            if len(key) != 32:
                raise ValueError(f"密钥文件长度非法: {len(key)}，期望 32 字节")
            return key
        key = AESGCM.generate_key(256)
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        self._key_file.write_bytes(key)
        return key

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_SIZE)
        return nonce + self._aesgcm.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if len(ciphertext) <= _NONCE_SIZE:
            raise InvalidTag()
        nonce, body = ciphertext[:_NONCE_SIZE], ciphertext[_NONCE_SIZE:]
        return self._aesgcm.decrypt(nonce, body, None)


_crypto: CryptoService | None = None


def get_crypto() -> CryptoService:
    global _crypto
    if _crypto is None:
        from app.config import settings

        _crypto = CryptoService(settings.secret_key_file)
    return _crypto


def reset_crypto_singleton() -> None:
    global _crypto
    _crypto = None