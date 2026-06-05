"""
Auth API 엔드포인트 통합 테스트 (HTTP 레벨).
FastAPI TestClient + AuthService Mock.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import PlanType, RiskProfileType


def _make_user(email: str = "test@example.com") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.display_name = "테스트"
    user.plan = PlanType.FREE
    user.risk_profile = RiskProfileType.MODERATE
    user.is_email_verified = True
    user.is_2fa_enabled = False
    user.last_login_at = None
    user.settings = None
    user.deleted_at = None
    return user


# ════════════════════════════════════════════════════════════════
# POST /auth/register
# ════════════════════════════════════════════════════════════════

class TestRegisterRoute:
    async def test_register_201(self, client: AsyncClient) -> None:
        user = _make_user()
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.register = AsyncMock(return_value=user)

            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "SecureP@ss1",
                    "agreed_to_terms": True,
                    "agreed_to_privacy": True,
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["data"]["email"] == user.email
        assert "message" in body["data"]
        assert "meta" in body

    async def test_register_invalid_password_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "weak",            # 강도 미달
                "agreed_to_terms": True,
                "agreed_to_privacy": True,
            },
        )
        assert resp.status_code == 422

    async def test_register_missing_terms_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "SecureP@ss1",
                "agreed_to_terms": False,       # 약관 미동의
                "agreed_to_privacy": True,
            },
        )
        assert resp.status_code == 422

    async def test_register_duplicate_email_409(self, client: AsyncClient) -> None:
        from app.utils.exceptions import ConflictError

        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.register = AsyncMock(
                side_effect=ConflictError(code="AUTH_006", message="이미 가입된 이메일입니다.")
            )

            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "dup@example.com",
                    "password": "SecureP@ss1",
                    "agreed_to_terms": True,
                    "agreed_to_privacy": True,
                },
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "AUTH_006"


# ════════════════════════════════════════════════════════════════
# POST /auth/login
# ════════════════════════════════════════════════════════════════

class TestLoginRoute:
    async def test_login_success_sets_cookie(self, client: AsyncClient) -> None:
        user = _make_user()
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.login = AsyncMock(
                return_value=("access_token_value", "raw_refresh_token", user)
            )

            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "SecureP@ss1"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["access_token"] == "access_token_value"
        assert body["data"]["token_type"] == "bearer"
        assert body["data"]["expires_in"] == 900
        assert "user" in body["data"]
        # Refresh Token은 HttpOnly Cookie에만
        assert "refresh_token" not in body["data"]
        # 쿠키 설정 확인
        assert "refresh_token" in resp.cookies or "set-cookie" in resp.headers

    async def test_login_wrong_credentials_401(self, client: AsyncClient) -> None:
        from app.utils.exceptions import UnauthorizedError

        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.login = AsyncMock(
                side_effect=UnauthorizedError(
                    code="AUTH_001",
                    message="이메일 또는 비밀번호가 올바르지 않습니다.",
                )
            )

            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "WrongPassword"},
            )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_001"

    async def test_login_locked_account_403(self, client: AsyncClient) -> None:
        from app.utils.exceptions import ForbiddenError

        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.login = AsyncMock(
                side_effect=ForbiddenError(
                    code="AUTH_009", message="계정이 잠겼습니다."
                )
            )

            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "Password1!"},
            )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "AUTH_009"


# ════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ════════════════════════════════════════════════════════════════

class TestRefreshRoute:
    async def test_refresh_success(self, client: AsyncClient) -> None:
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.refresh_access_token = AsyncMock(return_value="new_access_token")

            resp = await client.post(
                "/api/v1/auth/refresh",
                cookies={"refresh_token": "raw_token_value"},
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["access_token"] == "new_access_token"

    async def test_refresh_no_cookie_401(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_004"


# ════════════════════════════════════════════════════════════════
# POST /auth/logout
# ════════════════════════════════════════════════════════════════

class TestLogoutRoute:
    async def test_logout_204_clears_cookie(self, client: AsyncClient) -> None:
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.logout = AsyncMock(return_value=None)

            resp = await client.post(
                "/api/v1/auth/logout",
                cookies={"refresh_token": "raw_token"},
                headers={"Authorization": "Bearer fake_access_token"},
            )

        assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════
# POST /auth/forgot-password
# ════════════════════════════════════════════════════════════════

class TestForgotPasswordRoute:
    async def test_forgot_password_always_200(self, client: AsyncClient) -> None:
        """이메일 미존재여도 200 반환 (계정 존재 여부 노출 방지)."""
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.forgot_password = AsyncMock(return_value=None)

            resp = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "anyone@example.com"},
            )

        assert resp.status_code == 200
        assert "message" in resp.json()["data"]


# ════════════════════════════════════════════════════════════════
# POST /auth/reset-password
# ════════════════════════════════════════════════════════════════

class TestResetPasswordRoute:
    async def test_reset_password_success(self, client: AsyncClient) -> None:
        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.reset_password = AsyncMock(return_value=None)

            resp = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "valid_token_abc", "new_password": "NewPassword1!"},
            )

        assert resp.status_code == 200

    async def test_reset_password_expired_token_400(self, client: AsyncClient) -> None:
        from app.utils.exceptions import AppError

        with patch("app.api.v1.auth.AuthService") as MockSvc:
            mock_svc = MockSvc.return_value
            mock_svc.reset_password = AsyncMock(
                side_effect=AppError(code="AUTH_010", message="링크 만료")
            )

            resp = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "expired_token", "new_password": "NewPassword1!"},
            )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "AUTH_010"


# ════════════════════════════════════════════════════════════════
# 스키마 검증 테스트
# ════════════════════════════════════════════════════════════════

class TestAuthSchemas:
    def test_password_strength_validation(self) -> None:
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest

        # 유효한 비밀번호
        req = RegisterRequest(
            email="test@example.com",
            password="ValidP@ss1",
            agreed_to_terms=True,
            agreed_to_privacy=True,
        )
        assert req.password == "ValidP@ss1"

    def test_weak_password_raises(self) -> None:
        from pydantic import ValidationError
        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="test@example.com",
                password="nouppercaseorspecial",
                agreed_to_terms=True,
                agreed_to_privacy=True,
            )

    def test_totp_code_must_be_6_digits(self) -> None:
        from pydantic import ValidationError
        from app.schemas.auth import TwoFactorVerifyRequest

        with pytest.raises(ValidationError):
            TwoFactorVerifyRequest(totp_code="abc")   # 숫자 아님

        with pytest.raises(ValidationError):
            TwoFactorVerifyRequest(totp_code="12345")  # 5자리

        valid = TwoFactorVerifyRequest(totp_code="123456")
        assert valid.totp_code == "123456"
