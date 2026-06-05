"""TOTP 유틸리티 단위 테스트."""
from __future__ import annotations

import pyotp
import pytest

from app.utils.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    get_totp_uri,
    verify_backup_code,
    verify_totp,
)


class TestTOTPSecret:
    def test_generate_returns_base32_string(self) -> None:
        secret = generate_totp_secret()
        assert len(secret) == 32
        assert secret.isalpha() or secret.isupper()

    def test_encrypt_decrypt_roundtrip(self) -> None:
        secret = generate_totp_secret()
        encrypted = encrypt_totp_secret(secret)
        assert encrypted != secret
        assert decrypt_totp_secret(encrypted) == secret

    def test_encrypted_does_not_contain_plaintext(self) -> None:
        secret = generate_totp_secret()
        encrypted = encrypt_totp_secret(secret)
        assert secret not in encrypted


class TestTOTPVerification:
    def test_valid_current_code(self) -> None:
        secret = generate_totp_secret()
        code = pyotp.TOTP(secret).now()
        assert verify_totp(secret, code) is True

    def test_invalid_code_fails(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False

    def test_get_totp_uri_format(self) -> None:
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "user@example.com" in uri
        assert secret in uri


class TestBackupCodes:
    def test_generates_7_codes(self) -> None:
        plain, hashed = generate_backup_codes()
        assert len(plain) == 7
        assert len(hashed) == 7

    def test_plain_codes_format(self) -> None:
        plain, _ = generate_backup_codes()
        for code in plain:
            parts = code.split("-")
            assert len(parts) == 2
            assert all(len(p) == 4 for p in parts)

    def test_plain_and_hashed_differ(self) -> None:
        plain, hashed = generate_backup_codes()
        for p, h in zip(plain, hashed):
            assert p.replace("-", "") not in h

    def test_verify_valid_backup_code(self) -> None:
        plain, hashed = generate_backup_codes()
        is_valid, remaining = verify_backup_code(plain[0], hashed)
        assert is_valid is True
        assert len(remaining) == 6   # 사용된 코드 제거

    def test_verify_invalid_backup_code(self) -> None:
        _, hashed = generate_backup_codes()
        is_valid, remaining = verify_backup_code("0000-0000", hashed)
        assert is_valid is False
        assert len(remaining) == 7   # 변화 없음

    def test_backup_code_case_insensitive(self) -> None:
        plain, hashed = generate_backup_codes()
        code_upper = plain[0].upper()
        is_valid, _ = verify_backup_code(code_upper, hashed)
        assert is_valid is True
