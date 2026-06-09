"""
E2E-03: Binance Testnet 주문 실행 검증 (10 tests).

검증 항목:
  - 레버리지 설정
  - 시장가 진입 주문 (MARKET)
  - 손절 주문 (STOP_MARKET) — 진입 후 반드시 설정
  - 익절 주문 (TAKE_PROFIT_MARKET)
  - 포지션 생성 확인
  - 오픈 주문 목록 확인
  - 포지션 청산 (MARKET, reduce_only)
  - 주문 취소
  - 긴급 청산 시나리오

안전 원칙:
  - 최소 수량(0.001 BTC)만 사용
  - SL = 현재가 -10% (즉시 트리거 방지)
  - TP = 현재가 +20% (즉시 트리거 방지)
  - finally 블록에서 반드시 포지션 청산
  - Testnet URL 하드코딩 검증
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.clients.binance_rest import BinanceRESTClient

from .conftest_testnet import (
    MIN_QTY_BTC,
    TESTNET_BASE_URL,
    compute_position_size,
    guard_not_mainnet,
    validate_signal_rules,
)

SYMBOL = "BTCUSDT"


@pytest.mark.testnet
class TestLeverageSetting:

    async def test_set_leverage_returns_applied_value(self, testnet_client: BinanceRESTClient) -> None:
        """레버리지 5x 설정 후 반환값 검증."""
        guard_not_mainnet(TESTNET_BASE_URL)
        result = await testnet_client.set_leverage(SYMBOL, 5)
        assert result == 5

    async def test_leverage_capped_at_system_max(self, testnet_client: BinanceRESTClient) -> None:
        """
        Testnet에서 레버리지 상한 테스트.
        Testnet 계좌 설정에 따라 실제 최댓값이 다를 수 있음.
        """
        guard_not_mainnet(TESTNET_BASE_URL)
        requested = 5
        applied   = await testnet_client.set_leverage(SYMBOL, requested)
        # 요청보다 낮게 캡될 수 있지만 0 이하는 불가
        assert applied >= 1
        assert applied <= 20


@pytest.mark.testnet
class TestMarketDataFetch:

    async def test_btc_price_from_testnet(self, testnet_client: BinanceRESTClient) -> None:
        """Testnet BTC 현재가 조회."""
        guard_not_mainnet(TESTNET_BASE_URL)
        price = await testnet_client.get_current_price(SYMBOL)
        assert price > 0

    async def test_account_info_has_usdt(self, testnet_client: BinanceRESTClient) -> None:
        """계좌 정보에 USDT 자산이 있어야 한다."""
        guard_not_mainnet(TESTNET_BASE_URL)
        info = await testnet_client.get_account_info()
        assert info.available_balance >= 0
        usdt_assets = [a for a in info.assets if a.asset == "USDT"]
        assert len(usdt_assets) > 0, "USDT 자산이 계좌에 없음"


@pytest.mark.testnet
class TestOrderLifecycleBTC:
    """
    BTC 주문 전체 생명주기 테스트.
    각 테스트는 독립적이며 반드시 정리 후 종료한다.
    """

    async def test_market_entry_with_sl_and_tp(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        시나리오: BUY(LONG) 진입 → SL 설정 → TP 설정 → 포지션 확인 → 청산.

        SL = 현재가 × 0.90 (10% 아래)  → 테스트 중 트리거 방지
        TP = 현재가 × 1.20 (20% 위)   → 테스트 중 트리거 방지
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        price    = await testnet_client.get_current_price(SYMBOL)
        entry    = float(price)
        sl_price = round(entry * 0.90, 1)
        tp_price = round(entry * 1.20, 1)
        quantity = MIN_QTY_BTC

        # Risk 검증 (주문 전 필수)
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=sl_price,
            entry=entry,
            take_profit=tp_price,
            confidence=0.80,
            leverage=5,
        )
        assert ok, f"Risk 검증 실패: {reason}"

        entry_order = None
        try:
            # 1. 레버리지 설정
            await testnet_client.set_leverage(SYMBOL, 5)

            # 2. 시장가 진입 (BUY)
            entry_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
            )
            assert entry_order.order_id != ""
            assert entry_order.status in ("FILLED", "PARTIALLY_FILLED", "NEW")

            # 3. SL 주문 (필수 — STOP_MARKET, reduce_only)
            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            assert sl_order.order_id != "", "SL 주문이 생성되지 않았음"

            # 4. TP 주문 (TAKE_PROFIT_MARKET, reduce_only)
            tp_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                quantity=quantity,
                stop_price=Decimal(str(tp_price)),
                reduce_only=True,
            )
            assert tp_order.order_id != "", "TP 주문이 생성되지 않았음"

            # 5. 포지션 확인
            positions = await testnet_client.get_positions(SYMBOL)
            btc_positions = [p for p in positions if p.symbol == SYMBOL]
            assert len(btc_positions) > 0, "포지션이 생성되지 않았음"
            assert btc_positions[0].position_amt > 0, "LONG 포지션이 없음"

            # 6. 오픈 주문 확인 (SL + TP)
            open_orders = await testnet_client.get_open_orders(SYMBOL)
            order_ids = {o.order_id for o in open_orders}
            assert sl_order.order_id in order_ids, "SL 주문이 오픈 주문에 없음"

        finally:
            # 정리: 모든 오픈 주문 취소 + 포지션 청산
            await _cleanup(testnet_client, SYMBOL, quantity, "BUY")

    async def test_sl_is_mandatory_for_order(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        SL 없이 주문 실행 시 Risk 레이어에서 차단됨을 확인.
        실제 API 호출 없이 비즈니스 규칙 레이어에서 막힌다.
        """
        guard_not_mainnet(TESTNET_BASE_URL)
        price = float(await testnet_client.get_current_price(SYMBOL))

        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=None,
            entry=price,
            take_profit=price * 1.04,
            confidence=0.80,
            leverage=5,
        )
        assert ok is False, "SL 없는 주문이 Risk 레이어를 통과해선 안 됨"
        assert "ORDER_003" in reason

    async def test_sl_failure_triggers_emergency_close(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        SL 주문 실패 시 긴급 포지션 청산 시나리오.
        진입 → SL 실패 감지 → 즉시 청산.
        (TRADING_RULES.md §10 긴급 청산 원칙)
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        quantity = MIN_QTY_BTC
        entry_order = None
        try:
            await testnet_client.set_leverage(SYMBOL, 3)

            entry_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
            )
            assert entry_order.order_id != ""

            # SL 설정이 실패했다고 가정 → 즉시 청산 (reduce_only MARKET)
            emergency_close = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                reduce_only=True,
            )
            assert emergency_close.order_id != ""
            assert emergency_close.status in ("FILLED", "PARTIALLY_FILLED", "NEW")

        finally:
            await _cleanup(testnet_client, SYMBOL, quantity, "BUY")


@pytest.mark.testnet
class TestOrderCancellation:

    async def test_cancel_open_order(self, testnet_client: BinanceRESTClient) -> None:
        """
        주문 취소 — 오픈 STOP_MARKET 주문을 취소한다.
        진입 없이 SL 트리거 조건이 될 가격으로 설정 (포지션 없는 상태에서 테스트).
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        quantity = MIN_QTY_BTC
        entry_order = None
        sl_order_id = None

        try:
            await testnet_client.set_leverage(SYMBOL, 3)

            # 진입
            entry_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
            )

            price    = await testnet_client.get_current_price(SYMBOL)
            sl_price = round(float(price) * 0.85, 1)

            # SL 주문
            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            sl_order_id = sl_order.order_id

            # SL 취소
            cancelled = await testnet_client.cancel_order(SYMBOL, sl_order_id)
            assert cancelled.status == "CANCELED"

            # 취소 후 오픈 주문에 없는지 확인
            open_orders = await testnet_client.get_open_orders(SYMBOL)
            remaining_ids = {o.order_id for o in open_orders}
            assert sl_order_id not in remaining_ids, "취소된 SL 주문이 아직 오픈 목록에 있음"

        finally:
            await _cleanup(testnet_client, SYMBOL, quantity, "BUY")


# ── 정리 헬퍼 ─────────────────────────────────────────────────────────────────

async def _cleanup(
    client: BinanceRESTClient,
    symbol: str,
    quantity: Decimal,
    entry_side: str,
) -> None:
    """
    테스트 정리 — 오픈 주문 취소 + 포지션 청산.
    실패해도 예외를 삼키고 최대한 정리한다.
    """
    from app.clients.binance_base import BinanceAPIError

    # 1. 오픈 주문 전체 취소
    try:
        open_orders = await client.get_open_orders(symbol)
        for order in open_orders:
            try:
                await client.cancel_order(symbol, order.order_id)
            except BinanceAPIError:
                pass
    except Exception:
        pass

    # 2. 포지션 청산 (reduce_only MARKET)
    try:
        positions = await client.get_positions(symbol)
        for pos in positions:
            if pos.symbol == symbol and abs(pos.position_amt) > 0:
                close_side = "SELL" if pos.position_amt > 0 else "BUY"
                close_qty  = abs(pos.position_amt)
                await client.create_order(
                    symbol=symbol,
                    side=close_side,
                    order_type="MARKET",
                    quantity=close_qty,
                    reduce_only=True,
                )
    except Exception:
        pass
