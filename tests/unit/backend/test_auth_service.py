"""
AuthService 단위 테스트.
DB와 Redis를 Mock으로 교체하여 순수 비즈니스 로직만 검증.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PlanType, RiskProfileType
from app.utils.exceptions import AppError, ConflictError, ForbiddenError, UnauthorizedError


# ── 테스트용 User 픽스처 ────────────────────────────────────────────────────────

def _make_user(**kwargs) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = "$2b$12$placeholder_hash"
    user.plan = PlanType.FREE
    user.risk_profile = RiskProfileType.MODERATE
    user.is_email_verified = True
    user.is_2fa_enabled = False
    user.totp_secret_encrypted = None
    user.login_attempts = 0
    user.locked_until = None
    user.last_login_at = None
    user.display_name = None
    user.settings = None
    user.deleted_at = None
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def mock_user_repo():
    repo = AsyncMock()
    repo.email_exists = AsyncMock(return_value=False)
    repo.get_by_email = AsyncMock(return_value=None)
    repo.get_by_email_with_settings = AsyncMock(return_value=None)
    repo.get_by_id_with_settings = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update_fields = AsyncMock()
    repo.increment_login_attempts = AsyncMock(return_value=1)
    repo.reset_login_attempts = AsyncMock()
    repo.mark_email_verified = AsyncMock()
    repo.update_last_login = AsyncMock()
    repo.update_password = AsyncMock()
    repo.set_totp = AsyncMock()
    repo.enable_2fa = AsyncMock()
    repo.disable_2fa = AsyncMock()
    return repo


@pytest.fixture
def mock_token_repo():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_hash = AsyncMock(return_value=None)
    repo.delete_by_hash = AsyncMock()
    repo.delete_all_for_user = AsyncMock()
    return repo


def _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo):
    from app.services.auth_service import AuthService
    svc = AuthService(db=mock_db, redis=mock_redis)
    svc._users = mock_user_repo
    svc._tokens = mock_token_repo
    return svc


# ════════════════════════════════════════════════════════════════
# 회원가입 테스트
# ════════════════════════════════════════════════════════════════

class TestRegister:
    async def test_register_success(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        user = _make_user(is_email_verified=False)
        mock_user_repo.create.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with patch("app.services.auth_service.send_verification_email") as mock_email:
            mock_email.return_value = None
            result = await svc.register(
                email="new@example.com",
                password="SecureP@ss1",
                display_name="테스트",
            )

        assert result is user
        mock_user_repo.create.assert_called_once()
        mock_redis.set.assert_called()     # 인증 코드 Redis 저장

    async def test_register_duplicate_email_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_user_repo.email_exists.return_value = True
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(ConflictError) as exc:
            await svc.register("dup@example.com", "SecureP@ss1", None)
        assert exc.value.code == "AUTH_006"

    async def test_register_normalizes_email_to_lowercase(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        user = _make_user()
        mock_user_repo.create.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with patch("app.services.auth_service.send_verification_email"):
            await svc.register("USER@EXAMPLE.COM", "SecureP@ss1", None)

        call_kwargs = mock_user_repo.create.call_args
        assert call_kwargs.kwargs["email"] == "user@example.com"


# ════════════════════════════════════════════════════════════════
# 이메일 인증 테스트
# ════════════════════════════════════════════════════════════════

class TestVerifyEmail:
    async def test_verify_success(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        user = _make_user(is_email_verified=False)
        mock_user_repo.get_by_email_with_settings.return_value = user
        mock_redis.get = AsyncMock(side_effect=["123456", None])   # code, then attempts
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        access, refresh, returned_user = await svc.verify_email(
            email="test@example.com", code="123456"
        )
        assert access
        assert refresh
        assert returned_user is user
        mock_user_repo.mark_email_verified.assert_called_once()

    async def test_verify_expired_code_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_redis.get.return_value = None   # 코드 만료
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(AppError) as exc:
            await svc.verify_email("test@example.com", "123456")
        assert exc.value.code == "AUTH_007"

    async def test_verify_wrong_code_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_redis.get = AsyncMock(side_effect=["999999", "0"])   # stored=999999, attempts=0
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(AppError) as exc:
            await svc.verify_email("test@example.com", "123456")   # wrong code
        assert exc.value.code == "AUTH_008"
        assert exc.value.detail["attempts_remaining"] == 4


# ════════════════════════════════════════════════════════════════
# 로그인 테스트
# ════════════════════════════════════════════════════════════════

class TestLogin:
    async def test_login_success(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        from app.core.security import hash_password
        user = _make_user(password_hash=hash_password("SecureP@ss1"))
        mock_user_repo.get_by_email_with_settings.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        access, refresh, returned_user = await svc.login(
            email="test@example.com", password="SecureP@ss1"
        )
        assert access
        assert refresh
        mock_user_repo.reset_login_attempts.assert_called_once()
        mock_user_repo.update_last_login.assert_called_once()

    async def test_login_wrong_password_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        from app.core.security import hash_password
        user = _make_user(password_hash=hash_password("RealPassword1!"))
        mock_user_repo.get_by_email_with_settings.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(UnauthorizedError) as exc:
            await svc.login("test@example.com", "WrongPassword1!")
        assert exc.value.code == "AUTH_001"

    async def test_login_user_not_found_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_user_repo.get_by_email_with_settings.return_value = None
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(UnauthorizedError) as exc:
            await svc.login("ghost@example.com", "Password1!")
        assert exc.value.code == "AUTH_001"

    async def test_login_unverified_email_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        from app.core.security import hash_password
        user = _make_user(
            password_hash=hash_password("SecureP@ss1"),
            is_email_verified=False,
        )
        mock_user_repo.get_by_email_with_settings.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(UnauthorizedError) as exc:
            await svc.login("test@example.com", "SecureP@ss1")
        assert exc.value.code == "AUTH_002"

    async def test_login_locked_account_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        from app.core.security import hash_password
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = _make_user(
            password_hash=hash_password("SecureP@ss1"),
            locked_until=locked_until,
        )
        mock_user_repo.get_by_email_with_settings.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(ForbiddenError) as exc:
            await svc.login("test@example.com", "SecureP@ss1")
        assert exc.value.code == "AUTH_009"

    async def test_login_requires_totp_when_2fa_enabled(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        from app.core.security import hash_password
        user = _make_user(
            password_hash=hash_password("SecureP@ss1"),
            is_2fa_enabled=True,
            totp_secret_encrypted="encrypted_secret",
        )
        mock_user_repo.get_by_email_with_settings.return_value = user
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(AppError) as exc:
            await svc.login("test@example.com", "SecureP@ss1", totp_code=None)
        assert exc.value.code == "AUTH_003"
        assert exc.value.status_code == 422


# ════════════════════════════════════════════════════════════════
# 토큰 갱신 테스트
# ════════════════════════════════════════════════════════════════

class TestRefreshToken:
    async def test_refresh_success(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        stored_token = MagicMock()
        stored_token.user_id = uuid.uuid4()
        stored_token.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        mock_token_repo.get_by_hash.return_value = stored_token
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        new_token = await svc.refresh_access_token("raw_refresh_token_value")
        assert new_token   # Access Token 발급됨

    async def test_refresh_expired_token_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_token_repo.get_by_hash.return_value = None   # DB에 없음
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token("invalid_token")
        assert exc.value.code == "AUTH_004"


# ════════════════════════════════════════════════════════════════
# 비밀번호 재설정 테스트
# ════════════════════════════════════════════════════════════════

class TestPasswordReset:
    async def test_forgot_password_for_nonexistent_email_no_error(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        """이메일 미존재여도 에러 없음 — 계정 존재 여부 노출 방지."""
        mock_user_repo.get_by_email.return_value = None
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        # 예외 없이 완료되어야 함
        await svc.forgot_password("ghost@example.com")
        mock_redis.set.assert_not_called()   # 토큰 저장 안 됨

    async def test_reset_password_expired_token_raises(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        mock_redis.get.return_value = None   # 만료된 토큰
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        with pytest.raises(AppError) as exc:
            await svc.reset_password("expired_token", "NewPassword1!")
        assert exc.value.code == "AUTH_010"

    async def test_reset_password_success(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        user_id = str(uuid.uuid4())
        mock_redis.get.return_value = user_id
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)

        await svc.reset_password("valid_token", "NewPassword1!")
        mock_user_repo.update_password.assert_called_once()
        mock_token_repo.delete_all_for_user.assert_called_once()


# ════════════════════════════════════════════════════════════════
# 로그아웃 테스트
# ════════════════════════════════════════════════════════════════

class TestLogout:
    async def test_logout_deletes_refresh_token(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)
        await svc.logout("raw_refresh_token")
        mock_token_repo.delete_by_hash.assert_called_once()

    async def test_logout_without_token_no_error(
        self, mock_db, mock_redis, mock_user_repo, mock_token_repo
    ) -> None:
        svc = _make_service(mock_db, mock_redis, mock_user_repo, mock_token_repo)
        await svc.logout(None)   # 에러 없이 완료
        mock_token_repo.delete_by_hash.assert_not_called()
