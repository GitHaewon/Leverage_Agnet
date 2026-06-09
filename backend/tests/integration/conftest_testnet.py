"""
Binance Testnet E2E 테스트 — 공통 픽스처 및 유틸리티.

필수 환경변수:
  TESTNET_API_KEY    Binance Testnet API Key   (출금 권한 없어야 함)
  TESTNET_API_SECRET Binance Testnet API Secret

키가 없으면 모든 Testnet 테스트는 자동으로 Skip된다.

안전 원칙:
  - TESTNET_BASE_URL 하드코딩 — settings에서 읽지 않음
  - 모든 주문 테스트에 finally 정리 블록
  - 최소 수량(0.001 BTC / 0.01 ETH)만 사용
  - 실거래(mainnet) URL 사용 시 즉시 AssertionError
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

from app.clients.binance_rest import BinanceRESTClient

# ── 절대 변경 금지 ────────────────────────────────────────────────────────────
TESTNET_BASE_URL = "https://testnet.binancefuture.com"
MAINNET_BASE_URL = "https://fapi.binance.com"

# ── Testnet 최소 주문 수량 ─────────────────────────────────────────────────────
MIN_QTY_BTC = Decimal("0.001")
MIN_QTY_ETH = Decimal("0.01")

# ── TRADING_RULES.md §11.3 상수 ───────────────────────────────────────────────
MIN_CONFIDENCE   = 0.60
MIN_RR_RATIO     = 2.0
SYSTEM_MAX_LEVE  = 20
RISK_PER_TRADE_MIN = 0.005
RISK_PER_TRADE_MAX = 0.050


def _get_testnet_keys() -> tuple[str, str] | None:
    key    = os.environ.get("TESTNET_API_KEY", "").strip()
    secret = os.environ.get("TESTNET_API_SECRET", "").strip()
    if key and secret:
        return key, secret
    return None


def guard_not_mainnet(base_url: str) -> None:
    """실거래 URL 사용 시 즉시 실패."""
    assert MAINNET_BASE_URL not in base_url, (
        f"SECURITY VIOLATION: mainnet URL detected in test client: {base_url}"
    )
    assert "testnet" in base_url.lower(), (
        f"Expected testnet URL, got: {base_url}"
    )


# ── TRADING_RULES.md §7.1 포지션 사이징 공식 ─────────────────────────────────
def compute_position_size(
    balance: float,
    risk_per_trade: float,
    entry: float,
    stop_loss: float,
    leverage: int,
) -> tuple[Decimal, Decimal]:
    """
    (quantity_in_coins, margin_used_usdt) 반환.

    TRADING_RULES.md §7.1:
      sl_distance  = |entry - stop_loss|
      risk_amount  = balance × risk_per_trade
      quantity     = risk_amount / sl_distance           ← coins to buy
      margin_used  = (quantity × entry_price) / leverage
    """
    sl_distance = abs(entry - stop_loss)
    if sl_distance == 0:
        raise ValueError("sl_distance is zero — entry == stop_loss")
    risk_amount  = balance * risk_per_trade
    quantity     = risk_amount / sl_distance
    margin_used  = (quantity * entry) / leverage
    return Decimal(str(round(quantity, 3))), Decimal(str(round(margin_used, 2)))


# ── TRADING_RULES.md 인라인 Risk 검증 ─────────────────────────────────────────
def validate_signal_rules(
    direction: str,
    stop_loss: float | None,
    entry: float,
    take_profit: float,
    confidence: float,
    leverage: int,
) -> tuple[bool, str]:
    """
    DB 없이 TRADING_RULES.md 규칙을 직접 검증한다.
    Risk Agent와 1:1 대응.
    """
    if direction == "HOLD":
        return False, "REJECTED_HOLD: HOLD 시그널은 실행하지 않는다"

    if stop_loss is None or stop_loss <= 0:
        return False, "ORDER_003: 손절가 없는 주문 금지"

    if direction == "LONG":
        if stop_loss >= entry:
            return False, "ORDER_003: LONG SL이 진입가보다 높거나 같음"
        profit_dist = take_profit - entry
        loss_dist   = entry - stop_loss
    else:
        if stop_loss <= entry:
            return False, "ORDER_003: SHORT SL이 진입가보다 낮거나 같음"
        profit_dist = entry - take_profit
        loss_dist   = stop_loss - entry

    if loss_dist <= 0:
        return False, "RR_RATIO: 손실 거리 0 이하"

    rr = profit_dist / loss_dist
    if rr < MIN_RR_RATIO:
        return False, f"ORDER_004: R:R {rr:.2f} < {MIN_RR_RATIO} (최소 1:{MIN_RR_RATIO})"

    if confidence < MIN_CONFIDENCE:
        return False, f"LOW_CONFIDENCE: {confidence:.0%} < {MIN_CONFIDENCE:.0%}"

    if leverage > SYSTEM_MAX_LEVE:
        return False, f"LEVERAGE: {leverage}x > 시스템 상한 {SYSTEM_MAX_LEVE}x"

    return True, "OK"


# ── pytest 픽스처 ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def testnet_keys() -> tuple[str, str]:
    """
    TESTNET_API_KEY / TESTNET_API_SECRET 환경변수 로드.
    없으면 전체 세션 Skip.
    """
    keys = _get_testnet_keys()
    if keys is None:
        pytest.skip(
            "Testnet keys not set. "
            "Set TESTNET_API_KEY and TESTNET_API_SECRET to run testnet tests."
        )
    return keys


@pytest.fixture
async def testnet_client(testnet_keys: tuple[str, str]) -> BinanceRESTClient:
    """
    Testnet BinanceRESTClient 픽스처.
    사용 후 aclose()로 자격증명 메모리 제거.
    """
    key, secret = testnet_keys
    guard_not_mainnet(TESTNET_BASE_URL)
    client = BinanceRESTClient(
        api_key=key,
        api_secret=secret,
        base_url=TESTNET_BASE_URL,
    )
    yield client
    await client.aclose()
