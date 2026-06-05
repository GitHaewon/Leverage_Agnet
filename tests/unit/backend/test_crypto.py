"""app/utils/crypto.py 단위 테스트 — API Key 암호화 검증."""
from __future__ import annotations

import pytest

from app.utils.crypto import decrypt, encrypt


class TestAESGCMEncryption:
    def test_encrypt_returns_string(self) -> None:
        result = encrypt("my-binance-api-key")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_decrypt_recovers_original(self) -> None:
        original = "vmPUZE6mv9SD5VNHk4HlbGsG5A89..."
        token = encrypt(original)
        assert decrypt(token) == original

    def test_same_plaintext_different_ciphertext(self) -> None:
        """nonce가 랜덤이므로 같은 입력도 매번 다른 암호문."""
        t1 = encrypt("same-key")
        t2 = encrypt("same-key")
        assert t1 != t2

    def test_ciphertext_is_not_plaintext(self) -> None:
        """암호화된 값이 원문을 포함하지 않음 — 로그 노출 방지 검증."""
        api_key = "super-secret-binance-api-key"
        ciphertext = encrypt(api_key)
        assert api_key not in ciphertext

    def test_tampered_ciphertext_raises(self) -> None:
        """무결성 검증 실패 시 예외 발생 (GCM 태그 검증)."""
        token = encrypt("original")
        tampered = token[:-4] + "XXXX"
        with pytest.raises(Exception):
            decrypt(tampered)

    def test_empty_string_encrypts(self) -> None:
        token = encrypt("")
        assert decrypt(token) == ""

    def test_unicode_string_encrypts(self) -> None:
        korean = "바이낸스API키테스트"
        token = encrypt(korean)
        assert decrypt(token) == korean
