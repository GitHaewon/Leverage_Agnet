"""
TOTP (Time-based One-Time Password) 유틸리티.
pyotp 기반 2FA 구현.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg
from qrcode.image.pure import PyPNGImage

from app.utils.crypto import decrypt, encrypt


_ISSUER = "AI Trading Copilot"
_BACKUP_CODE_COUNT = 7


# ── TOTP 시크릿 ────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """32자 Base32 시크릿 생성."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    """Google Authenticator 등에서 인식하는 otpauth:// URI."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=_ISSUER)


def generate_qr_code_base64(uri: str) -> str:
    """QR 코드 PNG → base64 data URI."""
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """TOTP 코드 검증. valid_window=1 → ±30초 허용."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=valid_window)


# ── 시크릿 암호화/복호화 ──────────────────────────────────────────────────────

def encrypt_totp_secret(secret: str) -> str:
    """AES-256-GCM으로 TOTP 시크릿 암호화 후 저장."""
    return encrypt(secret)


def decrypt_totp_secret(encrypted: str) -> str:
    """복호화 — 검증 직전에만 호출하고 즉시 변수에서 제거."""
    return decrypt(encrypted)


# ── 백업 코드 ──────────────────────────────────────────────────────────────────

def generate_backup_codes() -> tuple[list[str], list[str]]:
    """
    백업 코드 생성.
    Returns:
        (plain_codes, hashed_codes)
        plain_codes: 사용자에게 표시 ("xxxx-xxxx" 형식)
        hashed_codes: DB에 저장 (SHA-256)
    """
    plain: list[str] = []
    hashed: list[str] = []

    for _ in range(_BACKUP_CODE_COUNT):
        raw = secrets.token_hex(4)                    # 8 hex chars
        formatted = f"{raw[:4]}-{raw[4:]}"            # "a1b2-c3d4"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        plain.append(formatted)
        hashed.append(digest)

    return plain, hashed


def verify_backup_code(plain_code: str, hashed_codes: list[str]) -> tuple[bool, list[str]]:
    """
    백업 코드 검증.
    Returns:
        (is_valid, remaining_codes)
        사용된 코드는 remaining_codes에서 제거됨.
    """
    raw = plain_code.replace("-", "").lower()
    digest = hashlib.sha256(raw.encode()).hexdigest()

    if digest in hashed_codes:
        remaining = [h for h in hashed_codes if h != digest]
        return True, remaining
    return False, hashed_codes
