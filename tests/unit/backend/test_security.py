"""app/core/security.py 단위 테스트."""
from __future__ import annotations

import time

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_different_from_plain(self) -> None:
        hashed = hash_password("mysecret123!")
        assert hashed != "mysecret123!"

    def test_verify_correct_password(self) -> None:
        hashed = hash_password("mysecret123!")
        assert verify_password("mysecret123!", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("mysecret123!")
        assert verify_password("wrongpassword", hashed) is False

    def test_same_password_different_hashes(self) -> None:
        """bcrypt는 매번 다른 salt → 같은 평문도 다른 해시."""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2


class TestJWT:
    def test_access_token_decodes_correctly(self) -> None:
        token = create_access_token("user-uuid-123")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-uuid-123"
        assert payload["type"] == "access"

    def test_refresh_token_decodes_correctly(self) -> None:
        token = create_refresh_token("user-uuid-456")
        payload = decode_refresh_token(token)
        assert payload["sub"] == "user-uuid-456"
        assert payload["type"] == "refresh"

    def test_access_and_refresh_tokens_are_different(self) -> None:
        access = create_access_token("uid")
        refresh = create_refresh_token("uid")
        assert access != refresh

    def test_access_token_has_jti(self) -> None:
        """각 토큰에 고유 ID — Refresh Token 재사용 방지에 필요."""
        t1 = create_access_token("uid")
        t2 = create_access_token("uid")
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]

    def test_access_token_verified_with_wrong_secret_fails(self) -> None:
        """refresh secret으로 access token을 검증하면 실패해야 함."""
        token = create_access_token("uid")
        with pytest.raises(JWTError):
            decode_refresh_token(token)

    def test_tampered_token_fails(self) -> None:
        token = create_access_token("uid")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_extra_claims_in_access_token(self) -> None:
        token = create_access_token("uid", extra={"plan": "pro", "role": "user"})
        payload = decode_access_token(token)
        assert payload["plan"] == "pro"
        assert payload["role"] == "user"
