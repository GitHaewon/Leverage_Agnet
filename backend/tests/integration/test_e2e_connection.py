"""
E2E-01: Binance Testnet 연결 검증 (6 tests).

검증 항목:
  - Testnet URL 안전 확인
  - API Key 인증 성공
  - 출금 권한 없음 확인 (절대 규칙)
  - Futures 거래 권한 확인
  - USDT 잔고 조회
  - BTC / ETH 현재가 조회

모든 테스트는 TESTNET_API_KEY / TESTNET_API_SECRET 환경변수가 없으면 Skip.
"""
from __future__ import annotations

import pytest

from .conftest_testnet import (
    MAINNET_BASE_URL,
    TESTNET_BASE_URL,
    guard_not_mainnet,
)


@pytest.mark.testnet
class TestTestnetConnection:

    def test_testnet_url_does_not_contain_mainnet(self) -> None:
        """URL 안전 검증 — 절대로 mainnet URL을 사용해선 안 된다."""
        guard_not_mainnet(TESTNET_BASE_URL)   # raises if mainnet
        assert "testnet" in TESTNET_BASE_URL.lower()
        assert MAINNET_BASE_URL not in TESTNET_BASE_URL

    async def test_api_key_validates_against_testnet(self, testnet_client) -> None:
        """
        API Key 권한 검증.
        Testnet에서 /fapi/v2/account 가 정상 응답해야 한다.
        """
        result = await testnet_client.validate_api_key()
        assert result is not None, "validate_api_key() returned None"

    async def test_withdraw_permission_is_not_granted(self, testnet_client) -> None:
        """
        출금 권한 차단 확인 (CLAUDE.md 절대 규칙 #5).
        has_withdraw=True이면 이 Key는 등록 자격 없음.
        """
        result = await testnet_client.validate_api_key()
        assert result.has_withdraw is False, (
            "SECURITY VIOLATION: 출금 권한이 있는 API Key가 감지됐습니다. "
            "Testnet Key에서 'Enable Withdrawals'를 즉시 해제하세요."
        )

    async def test_futures_trading_permission_is_granted(self, testnet_client) -> None:
        """Futures 거래 권한이 있어야 자동매매 가능."""
        result = await testnet_client.validate_api_key()
        assert result.can_trade is True, (
            "Futures 거래 권한이 없습니다. "
            "Testnet API Key에 'Enable Futures' 권한을 추가하세요."
        )
        assert result.can_futures_trade is True

    async def test_usdt_balance_is_positive(self, testnet_client) -> None:
        """
        Testnet 계좌에 USDT 잔고가 있어야 주문 테스트가 가능하다.
        Testnet 잔고가 0이면 testnet.binancefuture.com에서 충전 필요.
        """
        result = await testnet_client.validate_api_key()
        assert result.balance_usdt >= 0, "balance_usdt는 음수일 수 없음"
        if result.balance_usdt == 0:
            pytest.skip(
                "Testnet USDT 잔고가 0입니다. "
                "https://testnet.binancefuture.com 에서 충전 후 재시도."
            )

    async def test_current_price_btc_is_positive(self, testnet_client) -> None:
        """BTC 현재가 조회 — Testnet 시장 데이터 연결 확인."""
        price = await testnet_client.get_current_price("BTCUSDT")
        assert price > 0, f"BTC 가격이 0 이하: {price}"
        # Testnet 가격은 실제 시장과 크게 다를 수 있음 (수천 ~ 수십만 달러 범위)
        assert price > 100, f"BTC 가격이 비정상적으로 낮음: {price}"
