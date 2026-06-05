"""
AuthService — 인증 비즈니스 로직 전담.

레이어 규칙: Service → Repository → Model
API Route는 이 클래스만 호출하고 직접 DB를 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import UserInToken
from app.services.email_service import (
    send_password_reset_email,
    send_verification_email,
)
from app.utils.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
from app.utils.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_qr_code_base64,
    generate_totp_secret,
    get_totp_uri,
    verify_totp,
)

# ── Redis 키 패턴 ─────────────────────────────────────────────────────────────
_KEY_EMAIL_CODE = "email_verify:{email}"          # 인증 코드
_KEY_EMAIL_ATTEMPTS = "email_verify_attempts:{email}"  # 실패 횟수
_KEY_RESEND_COOLDOWN = "resend_cooldown:{email}"  # 재발송 쿨다운
_KEY_PWD_RESET = "pwd_reset:{token}"              # 비밀번호 재설정 토큰

# ── 상수 ──────────────────────────────────────────────────────────────────────
_EMAIL_CODE_TTL = 300        # 5분
_RESEND_COOLDOWN_TTL = 60    # 1분
_PWD_RESET_TTL = 1800        # 30분
_MAX_VERIFY_ATTEMPTS = 5
_MAX_LOGIN_ATTEMPTS = 5
_LOCK_DURATION_MINUTES = 15


def _hash_token(raw: str) -> str:
    """SHA-256 해시 — Refresh Token을 DB에 안전하게 저장."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _build_user_in_token(user: User) -> UserInToken:
    is_onboarding = user.settings is not None
    return UserInToken(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        plan=user.plan,
        risk_profile=user.risk_profile,
        is_email_verified=user.is_email_verified,
        is_2fa_enabled=user.is_2fa_enabled,
        is_onboarding_completed=is_onboarding,
        last_login_at=user.last_login_at,
    )


class AuthService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis) -> None:
        self._db = db
        self._redis = redis
        self._users = UserRepository(db)
        self._tokens = RefreshTokenRepository(db)

    # ════════════════════════════════════════════════════════════════
    # 회원가입
    # ════════════════════════════════════════════════════════════════

    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None,
    ) -> User:
        email = email.lower()

        if await self._users.email_exists(email):
            raise ConflictError(code="AUTH_006", message="이미 가입된 이메일입니다.")

        hashed = hash_password(password)
        user = await self._users.create(
            email=email,
            password_hash=hashed,
            display_name=display_name,
        )
        await self._db.commit()
        await self._db.refresh(user)

        # 인증 코드 발송
        await self._send_verification_code(email)

        return user

    async def _send_verification_code(self, email: str) -> None:
        """6자리 인증 코드 생성 → Redis 저장 → 이메일 발송."""
        code = f"{secrets.randbelow(1000000):06d}"
        key = _KEY_EMAIL_CODE.format(email=email)
        att_key = _KEY_EMAIL_ATTEMPTS.format(email=email)

        await self._redis.set(key, code, ex=_EMAIL_CODE_TTL)
        await self._redis.delete(att_key)    # 이전 시도 횟수 초기화
        await send_verification_email(email, code)

    # ════════════════════════════════════════════════════════════════
    # 이메일 인증
    # ════════════════════════════════════════════════════════════════

    async def verify_email(
        self,
        email: str,
        code: str,
        request_ip: str | None = None,
        device_info: str | None = None,
    ) -> tuple[str, str, User]:
        """
        Returns: (access_token, raw_refresh_token, user)
        """
        email = email.lower()
        code_key = _KEY_EMAIL_CODE.format(email=email)
        att_key = _KEY_EMAIL_ATTEMPTS.format(email=email)

        stored_code = await self._redis.get(code_key)
        if stored_code is None:
            raise AppError(
                code="AUTH_007",
                message="인증 코드가 만료되었습니다. 재발송을 요청하세요.",
            )

        # 시도 횟수 추적
        attempts = int(await self._redis.get(att_key) or 0)
        if stored_code != code:
            new_attempts = attempts + 1
            await self._redis.set(att_key, new_attempts, ex=_EMAIL_CODE_TTL)

            if new_attempts >= _MAX_VERIFY_ATTEMPTS:
                await self._redis.delete(code_key)
                await self._redis.delete(att_key)
                raise AppError(
                    code="AUTH_008",
                    message="인증 코드가 올바르지 않습니다. 코드가 무효화되었습니다.",
                    detail={"attempts_remaining": 0},
                )
            raise AppError(
                code="AUTH_008",
                message="인증 코드가 올바르지 않습니다.",
                detail={"attempts_remaining": _MAX_VERIFY_ATTEMPTS - new_attempts},
            )

        # 코드 일치 → Redis 정리
        await self._redis.delete(code_key)
        await self._redis.delete(att_key)

        user = await self._users.get_by_email_with_settings(email)
        if user is None:
            raise AppError(code="NOT_FOUND_001", message="사용자를 찾을 수 없습니다.")

        await self._users.mark_email_verified(user.id)
        await self._db.commit()
        await self._db.refresh(user)

        access_token = create_access_token(str(user.id))
        raw_refresh = await self._create_refresh_token(user.id, request_ip, device_info)

        return access_token, raw_refresh, user

    async def resend_verification(self, email: str) -> None:
        email = email.lower()
        cooldown_key = _KEY_RESEND_COOLDOWN.format(email=email)

        if await self._redis.exists(cooldown_key):
            raise AppError(
                code="RATE_001",
                message="재발송은 1분 후에 다시 시도할 수 있습니다.",
                status_code=429,
                detail={"retry_after_seconds": _RESEND_COOLDOWN_TTL},
            )

        user = await self._users.get_by_email(email)
        if user and not user.is_email_verified:
            await self._send_verification_code(email)
            await self._redis.set(cooldown_key, 1, ex=_RESEND_COOLDOWN_TTL)

        # 이메일 미존재여도 동일 응답 (계정 존재 여부 노출 방지)

    # ════════════════════════════════════════════════════════════════
    # 로그인
    # ════════════════════════════════════════════════════════════════

    async def login(
        self,
        email: str,
        password: str,
        totp_code: str | None = None,
        request_ip: str | None = None,
        device_info: str | None = None,
    ) -> tuple[str, str, User]:
        email = email.lower()
        user = await self._users.get_by_email_with_settings(email)

        # 계정 미존재 — timing attack 방지를 위해 hash 연산 실행
        if user is None:
            hash_password(password)   # 타이밍 동일하게 유지
            raise UnauthorizedError(
                code="AUTH_001",
                message="이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        # 계정 잠금 체크
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise ForbiddenError(
                code="AUTH_009",
                message="로그인 시도 5회 초과로 계정이 잠겼습니다.",
            )

        # 비밀번호 검증
        if not verify_password(password, user.password_hash):
            new_count = await self._users.increment_login_attempts(user.id)
            await self._db.commit()

            if new_count >= _MAX_LOGIN_ATTEMPTS:
                locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=_LOCK_DURATION_MINUTES
                )
                await self._users.update_fields(user.id, locked_until=locked_until)
                await self._db.commit()
                raise ForbiddenError(
                    code="AUTH_009",
                    message="로그인 시도 5회 초과로 계정이 잠겼습니다.",
                )

            raise UnauthorizedError(
                code="AUTH_001",
                message="이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        # 이메일 미인증
        if not user.is_email_verified:
            raise UnauthorizedError(code="AUTH_002", message="이메일 인증이 필요합니다.")

        # 2FA 체크
        if user.is_2fa_enabled:
            if not totp_code:
                raise AppError(
                    code="AUTH_003",
                    message="2FA 코드를 입력해주세요.",
                    status_code=422,
                    detail={"requires_totp": True},
                )
            secret = decrypt_totp_secret(user.totp_secret_encrypted)  # type: ignore[arg-type]
            if not verify_totp(secret, totp_code):
                raise UnauthorizedError(
                    code="AUTH_003", message="2FA 코드가 올바르지 않습니다."
                )

        # 로그인 성공 처리
        await self._users.reset_login_attempts(user.id)
        await self._users.update_last_login(user.id, request_ip)
        await self._db.commit()
        await self._db.refresh(user)

        access_token = create_access_token(str(user.id))
        raw_refresh = await self._create_refresh_token(user.id, request_ip, device_info)

        return access_token, raw_refresh, user

    # ════════════════════════════════════════════════════════════════
    # 토큰 갱신
    # ════════════════════════════════════════════════════════════════

    async def refresh_access_token(self, raw_refresh_token: str) -> str:
        """
        Refresh Token 쿠키 → 새 Access Token 발급.
        Refresh Token은 재사용하지 않는다 (token rotation 없음 — MVP 단순화).
        """
        token_hash = _hash_token(raw_refresh_token)
        stored = await self._tokens.get_by_hash(token_hash)

        if stored is None or stored.expires_at < datetime.now(timezone.utc):
            raise UnauthorizedError(
                code="AUTH_004", message="세션이 만료되었습니다. 다시 로그인해주세요."
            )

        return create_access_token(str(stored.user_id))

    # ════════════════════════════════════════════════════════════════
    # 로그아웃
    # ════════════════════════════════════════════════════════════════

    async def logout(self, raw_refresh_token: str | None) -> None:
        if raw_refresh_token:
            token_hash = _hash_token(raw_refresh_token)
            await self._tokens.delete_by_hash(token_hash)
            await self._db.commit()

    # ════════════════════════════════════════════════════════════════
    # 비밀번호 재설정
    # ════════════════════════════════════════════════════════════════

    async def forgot_password(self, email: str) -> None:
        email = email.lower()
        user = await self._users.get_by_email(email)

        # 이메일 미존재여도 동일 응답 (계정 존재 여부 노출 방지)
        if user is None or not user.is_email_verified:
            return

        reset_token = secrets.token_urlsafe(32)
        key = _KEY_PWD_RESET.format(token=reset_token)
        await self._redis.set(key, str(user.id), ex=_PWD_RESET_TTL)
        await send_password_reset_email(email, reset_token)

    async def reset_password(self, token: str, new_password: str) -> None:
        key = _KEY_PWD_RESET.format(token=token)
        user_id_str = await self._redis.get(key)

        if user_id_str is None:
            raise AppError(
                code="AUTH_010",
                message="비밀번호 재설정 링크가 만료되었습니다.",
            )

        await self._redis.delete(key)

        user_id = uuid.UUID(user_id_str)
        new_hash = hash_password(new_password)
        await self._users.update_password(user_id, new_hash)

        # 모든 기기 세션 종료
        await self._tokens.delete_all_for_user(user_id)
        await self._db.commit()

    # ════════════════════════════════════════════════════════════════
    # 2FA
    # ════════════════════════════════════════════════════════════════

    async def enable_2fa_start(
        self, user: User
    ) -> tuple[str, str, str, list[str]]:
        """
        2FA 활성화 시작 — QR 코드 및 백업 코드 반환.
        아직 DB에 저장하지 않는다. verify_2fa() 호출 시 저장.

        Returns: (qr_code_url, qr_code_base64_image, secret, backup_codes_plain)
        """
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, user.email)
        qr_image = generate_qr_code_base64(uri)
        plain_codes, hashed_codes = generate_backup_codes()

        # 임시 저장 (Redis TTL 10분 — 사용자가 QR 스캔 후 코드 입력할 시간)
        temp_key = f"totp_setup:{user.id}"
        await self._redis.set(
            temp_key,
            f"{secret}:{':'.join(hashed_codes)}",
            ex=600,
        )

        return uri, qr_image, secret, plain_codes

    async def verify_2fa_setup(self, user: User, totp_code: str) -> None:
        """
        TOTP 코드 검증 후 2FA 활성화 완료.
        Redis 임시 데이터를 DB에 영구 저장.
        """
        temp_key = f"totp_setup:{user.id}"
        raw = await self._redis.get(temp_key)
        if raw is None:
            raise AppError(
                code="AUTH_003",
                message="2FA 설정 세션이 만료되었습니다. 다시 시도해주세요.",
            )

        parts = raw.split(":")
        secret = parts[0]
        hashed_codes = parts[1:]

        if not verify_totp(secret, totp_code):
            raise UnauthorizedError(
                code="AUTH_003", message="2FA 코드가 올바르지 않습니다."
            )

        encrypted_secret = encrypt_totp_secret(secret)
        await self._users.set_totp(user.id, encrypted_secret, hashed_codes)
        await self._users.enable_2fa(user.id)
        await self._db.commit()
        await self._redis.delete(temp_key)

    async def disable_2fa(
        self, user: User, totp_code: str, password: str
    ) -> None:
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError(
                code="AUTH_001", message="비밀번호가 올바르지 않습니다."
            )
        if not user.totp_secret_encrypted:
            raise AppError(code="AUTH_003", message="2FA가 활성화되어 있지 않습니다.")

        secret = decrypt_totp_secret(user.totp_secret_encrypted)
        if not verify_totp(secret, totp_code):
            raise UnauthorizedError(
                code="AUTH_003", message="2FA 코드가 올바르지 않습니다."
            )

        await self._users.disable_2fa(user.id)
        await self._db.commit()

    # ════════════════════════════════════════════════════════════════
    # get_current_user 의존성용
    # ════════════════════════════════════════════════════════════════

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._users.get_by_id_with_settings(user_id)

    # ════════════════════════════════════════════════════════════════
    # Private helpers
    # ════════════════════════════════════════════════════════════════

    async def _create_refresh_token(
        self,
        user_id: uuid.UUID,
        ip_address: str | None,
        device_info: str | None,
    ) -> str:
        """임의의 128-char URL-safe 토큰 생성 → SHA-256 해시 DB 저장 → 원문 반환."""
        raw = secrets.token_urlsafe(64)   # 86자 URL-safe base64
        token_hash = _hash_token(raw)
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )
        await self._tokens.create(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device_info=device_info,
            ip_address=ip_address,
        )
        await self._db.commit()
        return raw
