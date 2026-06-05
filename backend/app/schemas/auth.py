from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import PlanType, RiskProfileType

# ── 비밀번호 강도 패턴 ────────────────────────────────────────────────────────────
_PASSWORD_RULES = [
    (re.compile(r"[A-Z]"), "대문자"),
    (re.compile(r"[a-z]"), "소문자"),
    (re.compile(r"\d"),    "숫자"),
    (re.compile(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~]"), "특수문자"),
]


def _validate_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")
    missing = [name for pattern, name in _PASSWORD_RULES if not pattern.search(password)]
    if missing:
        raise ValueError(
            f"비밀번호에 다음이 포함되어야 합니다: {', '.join(missing)}"
        )
    return password


# ════════════════════════════════════════════════════════════════
# Request Schemas
# ════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(None, min_length=2, max_length=30)
    agreed_to_terms: Literal[True]
    agreed_to_privacy: Literal[True]

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return _validate_password(v)


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str
    totp_code: str | None = Field(None, min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    pass   # 쿠키에서 읽음 — body 없음


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        return _validate_password(v)


class TwoFactorVerifyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorDisableRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    password: str


# ════════════════════════════════════════════════════════════════
# Response Schemas
# ════════════════════════════════════════════════════════════════

class RegisterData(BaseModel):
    user_id: uuid.UUID
    email: str
    message: str


class UserInToken(BaseModel):
    """로그인/이메일인증 응답에 포함되는 사용자 정보."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    plan: PlanType
    risk_profile: RiskProfileType
    is_email_verified: bool
    is_2fa_enabled: bool
    is_onboarding_completed: bool
    last_login_at: datetime | None


class TokenData(BaseModel):
    """Access Token 발급 응답."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900   # 15분 (초)
    user: UserInToken


class RefreshData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class MessageData(BaseModel):
    message: str


class ResendData(BaseModel):
    message: str
    expires_in: int


class TwoFactorEnableData(BaseModel):
    qr_code_url: str
    qr_code_image: str          # data:image/png;base64,...
    secret: str
    backup_codes: list[str]     # 7개, "xxxx-xxxx" 형식


class TwoFactorStatusData(BaseModel):
    is_2fa_enabled: bool
    message: str
