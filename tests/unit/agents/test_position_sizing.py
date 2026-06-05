"""
포지션 사이징 계산 단위 테스트 — TRADING_RULES.md §7.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.risk.sizing import (
    calculate_liquidation_distance,
    calculate_position_size,
    recalculate_avg_entry,
    resolve_final_leverage,
    round_to_lot_size,
    validate_position_size,
    validate_rr_ratio,
)
from agents.risk.models import PositionSizingResult


class TestResolveFinalLeverage:
    def test_system_max_caps_all(self) -> None:
        # System max는 20 — 어떤 요청도 초과 불가
        result = resolve_final_leverage(ai_recommended=25, user_max=25, plan="elite")
        assert result == 20

    def test_plan_free_max_5(self) -> None:
        result = resolve_final_leverage(ai_recommended=10, user_max=10, plan="free")
        assert result == 5

    def test_plan_pro_max_10(self) -> None:
        result = resolve_final_leverage(ai_recommended=15, user_max=15, plan="pro")
        assert result == 10

    def test_user_setting_wins_when_lower(self) -> None:
        # 사용자가 3x로 설정했으면 플랜 한도보다 낮으면 3x 적용
        result = resolve_final_leverage(ai_recommended=10, user_max=3, plan="pro")
        assert result == 3

    def test_ai_recommendation_wins_when_lowest(self) -> None:
        result = resolve_final_leverage(ai_recommended=2, user_max=10, plan="pro")
        assert result == 2


class TestRoundToLotSize:
    def test_btc_lot_size_0001(self) -> None:
        qty = round_to_lot_size(Decimal("0.02282"), "BTCUSDT")
        assert qty == Decimal("0.022")

    def test_always_floor_not_round(self) -> None:
        # 0.0229는 올림하면 0.023, 내림하면 0.022
        qty = round_to_lot_size(Decimal("0.0229"), "BTCUSDT")
        assert qty == Decimal("0.022")

    def test_eth_lot_size_001(self) -> None:
        qty = round_to_lot_size(Decimal("1.234"), "ETHUSDT")
        assert qty == Decimal("1.23")

    def test_exact_lot_size_unchanged(self) -> None:
        qty = round_to_lot_size(Decimal("0.010"), "BTCUSDT")
        assert qty == Decimal("0.010")


class TestValidateRRRatio:
    def test_long_valid_rr(self) -> None:
        ok, rr, reason = validate_rr_ratio(
            entry=Decimal("67450"),
            take_profit=Decimal("69200"),
            stop_loss=Decimal("66800"),
            direction="LONG",
        )
        assert ok is True
        assert float(rr) > 2.0

    def test_short_valid_rr(self) -> None:
        ok, rr, reason = validate_rr_ratio(
            entry=Decimal("67450"),
            take_profit=Decimal("65000"),
            stop_loss=Decimal("68275"),
            direction="SHORT",
        )
        assert ok is True

    def test_rr_below_minimum_rejected(self) -> None:
        # R:R = 1.5 < 2.0 최소
        ok, rr, reason = validate_rr_ratio(
            entry=Decimal("67450"),
            take_profit=Decimal("68425"),  # profit = 975
            stop_loss=Decimal("66800"),    # loss = 650, rr = 975/650 ≈ 1.5
            direction="LONG",
        )
        assert ok is False
        assert "ORDER_004" in reason

    def test_no_take_profit_rejected(self) -> None:
        ok, rr, reason = validate_rr_ratio(
            entry=Decimal("67450"),
            take_profit=None,
            stop_loss=Decimal("66800"),
            direction="LONG",
        )
        assert ok is False

    def test_wrong_stop_loss_direction_rejected(self) -> None:
        # LONG인데 SL이 진입가보다 위 → 잘못된 방향
        ok, rr, reason = validate_rr_ratio(
            entry=Decimal("67450"),
            take_profit=Decimal("69000"),
            stop_loss=Decimal("68000"),   # SL이 entry보다 위 → LONG에서 불가
            direction="LONG",
        )
        assert ok is False


class TestCalculatePositionSize:
    def test_example_from_trading_rules(self) -> None:
        """
        TRADING_RULES.md §7.1 핵심 공식 검증:
        balance=$10,000, risk=2%, entry=$67,450, sl=$66,800, leverage=5x
        → sl_distance = $650
        → risk_amount = $200
        → quantity   = $200 / $650 = 0.307 BTC → 0.307 (lot_size 내림)
        → margin     = 0.307 × $67,450 / 5 = $4,141.43
        → max_loss   = 0.307 × $650 = $199.55 ≈ $200

        주의: margin($4,141)이 계좌의 20% 한도($2,000)를 초과하므로
        실제 Risk Engine 통과 시 validate_position_size()에서 거부됨.
        """
        result = calculate_position_size(
            account_balance=Decimal("10000"),
            risk_per_trade=0.02,
            entry_price=Decimal("67450"),
            stop_loss_price=Decimal("66800"),
            leverage=5,
            take_profit_price=Decimal("69200"),
            symbol="BTCUSDT",
        )
        # quantity = floor(200/650 / 0.001) × 0.001 = 307 × 0.001 = 0.307
        assert result.quantity == Decimal("0.307")
        # max_loss = 0.307 × 650 = $199.55
        assert abs(result.max_loss - Decimal("199.55")) < Decimal("0.10")
        assert result.final_leverage == 5

    def test_max_loss_matches_sl_distance(self) -> None:
        """max_loss = quantity × sl_distance ≈ risk_amount (lot_size 반올림으로 근사)"""
        result = calculate_position_size(
            account_balance=Decimal("5000"),
            risk_per_trade=0.01,
            entry_price=Decimal("3500"),
            stop_loss_price=Decimal("3400"),
            leverage=3,
            symbol="ETHUSDT",
        )
        # sl_distance = 100, risk_amount = 50
        # quantity = 50/100 = 0.5 ETH → lot 0.01 → 0.50
        # max_loss = 0.50 × 100 = $50
        expected_max_loss = result.quantity * Decimal("100")
        assert abs(result.max_loss - expected_max_loss) < Decimal("0.01")

    def test_zero_sl_distance_raises(self) -> None:
        with pytest.raises(ValueError):
            calculate_position_size(
                account_balance=Decimal("10000"),
                risk_per_trade=0.02,
                entry_price=Decimal("67450"),
                stop_loss_price=Decimal("67450"),  # 동일 → 0 나눗셈
                leverage=5,
            )


class TestValidatePositionSize:
    def _make_result(
        self,
        quantity: str,
        margin: str,
        position_value: str,
        max_loss: str,
    ) -> PositionSizingResult:
        return PositionSizingResult(
            quantity=Decimal(quantity),
            margin_used=Decimal(margin),
            position_value=Decimal(position_value),
            max_loss=Decimal(max_loss),
            max_profit=Decimal("400"),
            final_leverage=5,
        )

    def test_valid_sizing_passes(self) -> None:
        result = self._make_result("0.022", "307.00", "1535.00", "200.00")
        ok, reason = validate_position_size(
            result,
            available_balance=Decimal("10000"),
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is True

    def test_below_min_quantity_rejected(self) -> None:
        result = self._make_result("0.0005", "33.00", "165.00", "20.00")  # < 0.001
        ok, reason = validate_position_size(
            result,
            available_balance=Decimal("10000"),
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is False
        assert "SIZING" in reason

    def test_insufficient_balance_rejected(self) -> None:
        result = self._make_result("0.022", "950.00", "4750.00", "200.00")
        ok, reason = validate_position_size(
            result,
            available_balance=Decimal("800"),   # 증거금 950 > 잔고 800
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is False

    def test_margin_exceeds_20pct_limit(self) -> None:
        # 잔고의 20% 한도 초과
        result = self._make_result("0.10", "2500.00", "12500.00", "1000.00")
        ok, reason = validate_position_size(
            result,
            available_balance=Decimal("10000"),
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is False
        assert "SIZING" in reason


class TestLiquidationDistance:
    def test_long_near_liquidation(self) -> None:
        # LONG: current=65000, liq=64000 → 거리 = (65000-64000)/65000 ≈ 1.5%
        dist = calculate_liquidation_distance("LONG", Decimal("65000"), Decimal("64000"))
        assert float(dist) == pytest.approx(0.0154, rel=0.01)

    def test_short_near_liquidation(self) -> None:
        dist = calculate_liquidation_distance("SHORT", Decimal("65000"), Decimal("66000"))
        assert float(dist) == pytest.approx(0.0154, rel=0.01)


class TestRecalculateAvgEntry:
    def test_equal_quantities(self) -> None:
        avg = recalculate_avg_entry(
            original_qty=Decimal("0.01"),
            original_entry=Decimal("67000"),
            dca_qty=Decimal("0.01"),
            dca_entry=Decimal("65000"),
        )
        assert avg == Decimal("66000")

    def test_different_quantities(self) -> None:
        avg = recalculate_avg_entry(
            original_qty=Decimal("0.02"),
            original_entry=Decimal("67000"),
            dca_qty=Decimal("0.01"),
            dca_entry=Decimal("64000"),
        )
        # (0.02×67000 + 0.01×64000) / 0.03 = (1340 + 640) / 0.03 = 66000
        assert avg == Decimal("66000")
