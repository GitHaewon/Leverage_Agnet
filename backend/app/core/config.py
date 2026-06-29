from __future__ import annotations

from decimal import Decimal
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
    # SHADOW_TRADING_ENABLED: Risk 검증 통과 시그널을 가상 체결로 기록
    # 실제 주문은 만들지 않는다.
    SHADOW_TRADING_ENABLED: bool = False
    SHADOW_INITIAL_BALANCE_USDT: Decimal = Decimal("10000")
    SHADOW_MIN_LONG_SCORE: float | None = None
    SHADOW_MIN_SHORT_SCORE: float | None = None
    SHADOW_MAX_RISK_SCORE: float | None = None
    SHADOW_AI_REVIEW_REQUIRED: bool = True
    # Binance USD-M virtual MARKET fills. Explicit conservative defaults.
    SHADOW_TAKER_FEE_RATE: Decimal = Decimal("0.0004")
    SHADOW_SLIPPAGE_BPS: Decimal = Decimal("5")
    SHADOW_FUNDING_RATE_PER_INTERVAL: Decimal = Decimal("0.0001")
    SHADOW_FUNDING_INTERVAL_HOURS: int = 8
    # [ASSUMPTION] Opt-in Shadow A/B defaults; both feature flags remain off.
    SHADOW_FAST_EXIT_V2_ENABLED: bool = False
    SHADOW_RISK_SIZING_V2_ENABLED: bool = False
    SHADOW_FAST_EXIT_MIN_SL_PCT: Decimal = Decimal("0.0025")
    SHADOW_FAST_EXIT_MAX_HOLD_SECONDS: int = 900
    SHADOW_FAST_EXIT_TP_PCT: Decimal = Decimal("0.006")
    SHADOW_FAST_EXIT_SL_PCT: Decimal = Decimal("0.003")
    SHADOW_FAST_EXIT_MIN_RR: Decimal = Decimal("2.0")
    SHADOW_RISK_PER_TRADE_PCT: Decimal = Decimal("0.01")
    SHADOW_SAFE_MAX_LEVERAGE: int = 5
    SHADOW_MIN_TP_COST_MULTIPLE: Decimal = Decimal("1.0")
    SHADOW_EXPERIMENT_LABEL: str = "fast_exit_v2_ab"
    SHADOW_MAX_PORTFOLIO_RISK_PCT: Decimal = Decimal("0.10")
    SHADOW_MAX_SINGLE_MARGIN_RATIO: Decimal = Decimal("0.20")
    SHADOW_MARGIN_BUFFER_RATIO: Decimal = Decimal("1.10")

    # ── Binance URL ─────────────────────────────────────────────────────────────
    BINANCE_TESTNET_BASE_URL: str = "https://testnet.binancefuture.com"
    BINANCE_MAINNET_BASE_URL: str = "https://fapi.binance.com"
    BINANCE_SPOT_TESTNET_URL: str = "https://testnet.binance.vision"   # 권한 검증용

    # ── Trading Safety Constants ────────────────────────────────────────────────
    SYSTEM_MAX_LEVERAGE: int = 20          # 절대 상한 (TRADING_RULES.md §1.1)

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5"

    # ── Memory Layer (Qdrant) ──────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    # 한국어 지원 다국어 임베딩 모델 — fastembed 지원 모델 중 선택
    # 변경 시 MEMORY_VECTOR_SIZE도 함께 수정 필요
    MEMORY_EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    MEMORY_VECTOR_SIZE: int = 384

    # ── Stripe ─────────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    # ── Telegram ───────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str = ""  # AlertDispatcher에 주입할 기본 chat_id (사용자별 재정의 가능)

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

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if not Decimal("0") <= self.SHADOW_TAKER_FEE_RATE <= Decimal("0.1"):
            raise ValueError("SHADOW_TAKER_FEE_RATE must be between 0 and 0.1")
        if not Decimal("0") <= self.SHADOW_SLIPPAGE_BPS <= Decimal("1000"):
            raise ValueError("SHADOW_SLIPPAGE_BPS must be between 0 and 1000")
        if (
            self.SHADOW_FUNDING_INTERVAL_HOURS <= 0
            or 24 % self.SHADOW_FUNDING_INTERVAL_HOURS
        ):
            raise ValueError("SHADOW_FUNDING_INTERVAL_HOURS must divide 24")
        if self.SHADOW_RISK_SIZING_V2_ENABLED and not self.SHADOW_FAST_EXIT_V2_ENABLED:
            raise ValueError(
                "SHADOW_RISK_SIZING_V2_ENABLED requires SHADOW_FAST_EXIT_V2_ENABLED"
            )
        if min(
            self.SHADOW_FAST_EXIT_MIN_SL_PCT,
            self.SHADOW_FAST_EXIT_TP_PCT,
            self.SHADOW_FAST_EXIT_SL_PCT,
            self.SHADOW_FAST_EXIT_MIN_RR,
            self.SHADOW_RISK_PER_TRADE_PCT,
            self.SHADOW_MIN_TP_COST_MULTIPLE,
        ) <= 0:
            raise ValueError("Shadow experiment percentages and ratios must be positive")
        if self.SHADOW_FAST_EXIT_MAX_HOLD_SECONDS <= 0:
            raise ValueError("SHADOW_FAST_EXIT_MAX_HOLD_SECONDS must be positive")
        if self.SHADOW_SAFE_MAX_LEVERAGE < 1:
            raise ValueError("SHADOW_SAFE_MAX_LEVERAGE must be >= 1")
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
