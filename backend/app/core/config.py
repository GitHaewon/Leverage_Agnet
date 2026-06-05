from __future__ import annotations

from typing import Any, Literal

from pydantic import PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────────
    APP_NAME: str = "AI Trading Copilot"
    APP_ENV: Literal["development", "staging", "production", "testing"] = "development"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ── API ────────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ── Security / JWT ─────────────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_REFRESH_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ───────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600
    DB_ECHO: bool = False

    # ── Redis ──────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn
    REDIS_MAX_CONNECTIONS: int = 20

    # ── Binance ────────────────────────────────────────────────────────────────
    BINANCE_TESTNET: bool = True
    BINANCE_ENCRYPT_KEY: str

    # ── Binance Feature Flags ──────────────────────────────────────────────────
    # LIVE_TRADING_ENABLED: CTO 승인 없이 절대 true로 변경 금지
    LIVE_TRADING_ENABLED: bool = False
    MOCK_TRADING_MODE: bool = False        # True = 실제 API 호출 없음 (개발/테스트)

    # ── Binance URL ─────────────────────────────────────────────────────────────
    BINANCE_TESTNET_BASE_URL: str = "https://testnet.binancefuture.com"
    BINANCE_MAINNET_BASE_URL: str = "https://fapi.binance.com"
    BINANCE_SPOT_TESTNET_URL: str = "https://testnet.binance.vision"   # 권한 검증용

    # ── Trading Safety Constants ────────────────────────────────────────────────
    SYSTEM_MAX_LEVERAGE: int = 20          # 절대 상한 (TRADING_RULES.md §1.1)

    # ── AI ─────────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # ── Stripe ─────────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    # ── Telegram ───────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str

    # ── SMTP ───────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@trading-copilot.com"

    # ── CORS ───────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Rate Limit ─────────────────────────────────────────────────────────────
    RATE_LIMIT_FREE: int = 60
    RATE_LIMIT_PRO: int = 300
    RATE_LIMIT_ELITE: int = 1000

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("CLAUDE_MODEL")
    @classmethod
    def validate_claude_model(cls, v: str) -> str:
        # claude-sonnet-4-6 외 사용 금지 (CLAUDE.md 절대 규칙)
        allowed = {"claude-sonnet-4-6"}
        if v not in allowed:
            raise ValueError(f"Unauthorized model: {v}. Only {allowed} is permitted.")
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")
            if self.BINANCE_TESTNET:
                raise ValueError("BINANCE_TESTNET must be False in production")
        # LIVE_TRADING_ENABLED=true이면 BINANCE_TESTNET=false여야 일관성 유지
        if self.LIVE_TRADING_ENABLED and self.BINANCE_TESTNET:
            raise ValueError(
                "LIVE_TRADING_ENABLED=true requires BINANCE_TESTNET=false. "
                "Review this setting carefully."
            )
        return self

    @property
    def binance_base_url(self) -> str:
        """현재 설정에 따른 Binance REST Base URL."""
        if self.BINANCE_TESTNET:
            return self.BINANCE_TESTNET_BASE_URL
        return self.BINANCE_MAINNET_BASE_URL

    @property
    def async_database_url(self) -> str:
        """asyncpg 드라이버용 URL 변환."""
        url = str(self.DATABASE_URL)
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_testing(self) -> bool:
        return self.APP_ENV == "testing"


settings = Settings()
