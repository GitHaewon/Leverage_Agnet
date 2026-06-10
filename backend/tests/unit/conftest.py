"""
단위 테스트 conftest — app.core.config 로드에 필요한 더미 환경변수 설정.

pydantic_settings는 Settings() 인스턴스 생성 시 env를 읽으므로
모듈 임포트 전에 os.environ을 준비해야 한다.
"""
import os

# 필수 env vars — 단위 테스트에서만 사용하는 더미값
_TEST_ENVS = {
    "JWT_SECRET":             "test-jwt-secret-key-minimum-32-characters-long!!",
    "JWT_REFRESH_SECRET":     "test-refresh-secret-key-minimum-32-chars-long!!",
    "DATABASE_URL":           "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    "REDIS_URL":              "redis://localhost:6379/0",
    "BINANCE_ENCRYPT_KEY":    "A" * 32,   # AES-256 = 32 바이트
    "ANTHROPIC_API_KEY":      "sk-ant-test-dummy-key",
    "STRIPE_SECRET_KEY":      "sk_test_dummy_key",
    "STRIPE_WEBHOOK_SECRET":  "whsec_test_dummy_secret",
    "TELEGRAM_BOT_TOKEN":     "1234567890:AAtest-bot-token",
}

for key, val in _TEST_ENVS.items():
    os.environ.setdefault(key, val)
