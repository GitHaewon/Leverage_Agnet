"""
E2E-04: Signal → Risk → Position → Execution 전체 파이프라인 검증 (8 tests).

이 파일은 전체 E2E 흐름을 하나의 연속 시나리오로 검증한다.

파이프라인:
  1. Market Data    : Testnet에서 실시간 BTC 가격 조회
  2. Signal Build   : 현재가 기반 유효 LONG/SHORT 시그널 구성
  3. Risk Gate      : validate_signal_rules() 통과 확인
  4. Position Size  : compute_position_size() 계산
  5. Order Execute  : set_leverage → MARKET 진입 → STOP_MARKET SL
  6. Position Verify: 포지션 생성 확인, 방향/수량/레버리지
  7. Cleanup        : 오픈 주문 취소 + 포지션 청산

성공 기준:
  - 모든 단계가 순서대로 완료됨
  - SL 없이는 어떤 단계도 실행 주문으로 이어지지 않음
  - finally 블록에서 포지션이 반드시 청산됨

Risk Manager 우회 금지 — TRADING_RULES.md §10
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
from .test_e2e_execution import _cleanup

SYMBOL = "BTCUSDT"
LEVERAGE = 5
RISK_PCT = 0.01    # 1% risk per trade


@pytest.mark.testnet
class TestFullPipelineLong:
    """
    LONG 방향 전체 파이프라인.
    Signal 구성 → Risk 검증 → 사이징 → 진입 → 확인 → 청산.
    """

    async def test_signal_to_position_long(self, testnet_client: BinanceRESTClient) -> None:
        """
        LONG 파이프라인 골든 패스.

        단계:
          1. BTC 실시간 가격 조회
          2. SL = -10%, TP = -20% 이상 (R:R >= 2.0) 시그널 구성
          3. Risk Gate 통과 확인
          4. 포지션 사이징 계산
          5. 레버리지 설정
          6. MARKET BUY 진입
          7. STOP_MARKET SL 설정 (필수)
          8. 포지션 생성 및 방향 확인
          9. 오픈 주문 목록에 SL 존재 확인
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        # ── 1. 현재가 조회 ──────────────────────────────────────────────────────
        price  = await testnet_client.get_current_price(SYMBOL)
        entry  = float(price)
        assert entry > 0, "현재가 조회 실패"

        # ── 2. 시그널 구성 ─────────────────────────────────────────────────────
        sl_price = round(entry * 0.90, 1)   # -10%
        tp_price = round(entry * 1.22, 1)   # +22% → R:R = 22/10 = 2.2
        confidence = 0.82
        signal = {
            "coin": "BTC",
            "direction": "LONG",
            "entry": entry,
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "confidence": confidence,
            "leverage": LEVERAGE,
        }

        # ── 3. Risk Gate ───────────────────────────────────────────────────────
        ok, reason = validate_signal_rules(
            direction=signal["direction"],
            stop_loss=signal["stop_loss"],
            entry=signal["entry"],
            take_profit=signal["take_profit"],
            confidence=signal["confidence"],
            leverage=signal["leverage"],
        )
        assert ok, f"Risk Gate 차단: {reason}"

        # ── 4. 포지션 사이징 ───────────────────────────────────────────────────
        info = await testnet_client.get_account_info()
        balance = float(info.available_balance)
        if balance <= 0:
            pytest.skip("Testnet 잔고 부족")

        qty_calc, margin_calc = compute_position_size(
            balance=balance,
            risk_per_trade=RISK_PCT,
            entry=entry,
            stop_loss=sl_price,
            leverage=LEVERAGE,
        )
        # 최솟값 보장
        quantity = max(qty_calc, MIN_QTY_BTC)
        assert quantity >= MIN_QTY_BTC

        try:
            # ── 5. 레버리지 설정 ───────────────────────────────────────────────
            applied_leverage = await testnet_client.set_leverage(SYMBOL, LEVERAGE)
            assert applied_leverage >= 1

            # ── 6. MARKET BUY 진입 ────────────────────────────────────────────
            entry_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
            )
            assert entry_order.order_id != "", "진입 주문 ID가 없음"
            assert entry_order.status in ("FILLED", "PARTIALLY_FILLED", "NEW")

            # ── 7. SL 설정 (Risk Manager Agent 의무 게이트) ────────────────────
            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            assert sl_order.order_id != "", "SL 주문이 생성되지 않음 — 즉시 포지션 청산 필요"

            # ── 8. 포지션 확인 ─────────────────────────────────────────────────
            positions = await testnet_client.get_positions(SYMBOL)
            btc_pos = [p for p in positions if p.symbol == SYMBOL and p.position_amt > 0]
            assert len(btc_pos) > 0, "LONG 포지션이 생성되지 않음"
            assert btc_pos[0].position_amt >= float(quantity) * 0.99

            # ── 9. SL이 오픈 주문에 있는지 확인 ───────────────────────────────
            open_orders = await testnet_client.get_open_orders(SYMBOL)
            order_ids = {o.order_id for o in open_orders}
            assert sl_order.order_id in order_ids, "SL 주문이 오픈 주문 목록에 없음"

        finally:
            await _cleanup(testnet_client, SYMBOL, quantity, "BUY")

    async def test_pipeline_rejects_signal_without_sl(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        SL 없는 시그널은 Risk Gate에서 차단되어 실행 단계에 도달하지 못한다.
        실제 주문 API는 호출되지 않는다.
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
        assert ok is False, "SL 없는 시그널이 Risk Gate를 통과함"

        # Risk Gate가 차단했으므로 실행 단계 없음 — 여기까지 오면 성공


@pytest.mark.testnet
class TestFullPipelineShort:
    """
    SHORT 방향 전체 파이프라인.
    """

    async def test_signal_to_position_short(self, testnet_client: BinanceRESTClient) -> None:
        """
        SHORT 파이프라인 골든 패스.

        SL = +10% (entry 위), TP = -22% (entry 아래, R:R 2.2x)
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        price  = await testnet_client.get_current_price(SYMBOL)
        entry  = float(price)
        sl_price = round(entry * 1.10, 1)   # +10% — SHORT SL은 위에 있어야 함
        tp_price = round(entry * 0.78, 1)   # -22% — R:R = 22/10 = 2.2
        confidence = 0.75
        quantity = MIN_QTY_BTC

        ok, reason = validate_signal_rules(
            direction="SHORT",
            stop_loss=sl_price,
            entry=entry,
            take_profit=tp_price,
            confidence=confidence,
            leverage=LEVERAGE,
        )
        assert ok, f"SHORT Risk Gate 차단: {reason}"

        try:
            await testnet_client.set_leverage(SYMBOL, LEVERAGE)

            # SELL 진입 (SHORT)
            entry_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
            )
            assert entry_order.order_id != ""

            # SHORT SL — BUY, reduce_only
            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            assert sl_order.order_id != "", "SHORT SL 주문 생성 실패"

            # 포지션 확인 (음수 position_amt = SHORT)
            positions = await testnet_client.get_positions(SYMBOL)
            short_pos = [p for p in positions if p.symbol == SYMBOL and p.position_amt < 0]
            assert len(short_pos) > 0, "SHORT 포지션이 생성되지 않음"

        finally:
            await _cleanup(testnet_client, SYMBOL, quantity, "SELL")


@pytest.mark.testnet
class TestPipelineEdgeCases:
    """파이프라인 엣지 케이스 및 경계값 검증."""

    async def test_minimum_size_order_executes(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        최소 수량(0.001 BTC)으로 주문이 실행되는지 확인.
        이 수량 미만이면 Binance API 오류가 발생해야 한다.
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        price    = float(await testnet_client.get_current_price(SYMBOL))
        sl_price = round(price * 0.90, 1)
        tp_price = round(price * 1.22, 1)

        ok, _ = validate_signal_rules(
            direction="LONG",
            stop_loss=sl_price,
            entry=price,
            take_profit=tp_price,
            confidence=0.80,
            leverage=3,
        )
        assert ok

        try:
            await testnet_client.set_leverage(SYMBOL, 3)

            order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=MIN_QTY_BTC,
            )
            assert order.order_id != ""

            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=MIN_QTY_BTC,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            assert sl_order.order_id != ""

        finally:
            await _cleanup(testnet_client, SYMBOL, MIN_QTY_BTC, "BUY")

    async def test_pipeline_state_clean_after_cleanup(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        청산 후 포지션이 남지 않는지 확인.
        이전 테스트 잔재가 없어야 한다.
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        # 정리 실행
        await _cleanup(testnet_client, SYMBOL, MIN_QTY_BTC, "BUY")

        # 청산 후 포지션 확인
        positions = await testnet_client.get_positions(SYMBOL)
        active = [p for p in positions if p.symbol == SYMBOL and abs(p.position_amt) > 0]

        # 청산 후에는 포지션이 없거나 매우 작아야 함
        if active:
            assert abs(active[0].position_amt) < 0.001, (
                f"청산 후 잔여 포지션 발견: {active[0].position_amt}"
            )

    async def test_high_confidence_signal_executes(
        self, testnet_client: BinanceRESTClient
    ) -> None:
        """
        신뢰도 90% 이상 시그널도 동일한 Risk Gate를 통과한다.
        """
        guard_not_mainnet(TESTNET_BASE_URL)

        price    = float(await testnet_client.get_current_price(SYMBOL))
        sl_price = round(price * 0.90, 1)
        tp_price = round(price * 1.22, 1)

        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=sl_price,
            entry=price,
            take_profit=tp_price,
            confidence=0.95,
            leverage=5,
        )
        assert ok, f"고신뢰도 시그널이 차단됨: {reason}"

        try:
            await testnet_client.set_leverage(SYMBOL, 5)

            order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="BUY",
                order_type="MARKET",
                quantity=MIN_QTY_BTC,
            )
            assert order.order_id != ""

            sl_order = await testnet_client.create_order(
                symbol=SYMBOL,
                side="SELL",
                order_type="STOP_MARKET",
                quantity=MIN_QTY_BTC,
                stop_price=Decimal(str(sl_price)),
                reduce_only=True,
            )
            assert sl_order.order_id != ""

        finally:
            await _cleanup(testnet_client, SYMBOL, MIN_QTY_BTC, "BUY")
