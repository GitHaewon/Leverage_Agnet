"""app/core/config.py 단위 테스트."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import settings


class TestSettings:
    def test_claude_model_is_approved(self) -> None:
        """CLAUDE.md 절대 규칙: claude-sonnet-4-6 외 사용 금지."""
        assert settings.CLAUDE_MODEL == "claude-sonnet-4-6"

    def test_binance_testnet_default_is_true(self) -> None:
        """실수로 메인넷에서 테스트하는 사고 방지."""
        assert settings.BINANCE_TESTNET is True

    def test_async_database_url_has_asyncpg_scheme(self) -> None:
        url = settings.async_database_url
        assert url.startswith("postgresql+asyncpg://"), (
            f"Expected postgresql+asyncpg:// scheme, got: {url}"
        )

    def test_async_database_url_no_plain_postgresql(self) -> None:
        url = settings.async_database_url
        assert not url.startswith("postgresql://")

    def test_cors_origins_is_list(self) -> None:
        assert isinstance(settings.CORS_ORIGINS, list)
        assert len(settings.CORS_ORIGINS) >= 1

    def test_jwt_tokens_are_not_empty(self) -> None:
        assert settings.JWT_SECRET
        assert settings.JWT_REFRESH_SECRET
        assert settings.JWT_SECRET != settings.JWT_REFRESH_SECRET

    def test_app_env_is_testing(self) -> None:
        assert settings.APP_ENV == "testing"

    def test_is_testing_property(self) -> None:
        assert settings.is_testing is True

    def test_is_production_property(self) -> None:
        assert settings.is_production is False

    def test_rate_limit_values(self) -> None:
        assert settings.RATE_LIMIT_FREE < settings.RATE_LIMIT_PRO < settings.RATE_LIMIT_ELITE


class TestSettingsValidation:
    def test_invalid_claude_model_raises(self) -> None:
        """claude-opus 등 비인가 모델은 설정 로드 시 오류 발생."""
        import os
        from importlib import reload

        original = os.environ.get("CLAUDE_MODEL")
        os.environ["CLAUDE_MODEL"] = "claude-opus-4-8"  # 금지 모델

        try:
            with pytest.raises(ValidationError, match="Unauthorized model"):
                from app.core import config as cfg_module
                reload(cfg_module)
                cfg_module.Settings()
        finally:
            if original:
                os.environ["CLAUDE_MODEL"] = original
            else:
                del os.environ["CLAUDE_MODEL"]

    def test_cors_origins_parsed_from_comma_string(self) -> None:
        """환경변수에서 콤마 구분 문자열을 리스트로 파싱."""
        import os
        from app.core.config import Settings

        original = os.environ.get("CORS_ORIGINS")
        os.environ["CORS_ORIGINS"] = "http://a.com,http://b.com"

        try:
            s = Settings()
            assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]
        finally:
            if original:
                os.environ["CORS_ORIGINS"] = original
