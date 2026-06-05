from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_SIZE = 12   # AES-GCM 표준 nonce 크기


def _get_key() -> bytes:
    key = settings.BINANCE_ENCRYPT_KEY
    # hex 또는 raw 32 바이트 문자열 모두 허용
    try:
        decoded = bytes.fromhex(key)
        if len(decoded) == 32:
            return decoded
    except ValueError:
        pass
    raw = key.encode()
    if len(raw) == 32:
        return raw
    raise ValueError("BINANCE_ENCRYPT_KEY must be 32 bytes (hex-encoded or raw)")


def encrypt(plaintext: str) -> str:
    """AES-256-GCM 암호화. nonce를 앞에 붙여 base64 반환."""
    key = _get_key()
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(token: str) -> str:
    """AES-256-GCM 복호화. 사용 즉시 반환값을 메모리에서 제거할 것."""
    key = _get_key()
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
