"""
Position Sizing Engine 단위 테스트 — 4가지 방법 검증.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from agents.risk.models import AccountState, RawSignal
from agents.risk.sizing_engine import PositionSizingEngine
from agents.risk.sizing_models import (
    SizingConfig,
    SizingMethod,
    SizingResult,
    TradeStatistics,
)


# ── 테스트 픽스처 ─────────────────────────────────────────────────────────────────

def _signal(
    direction: str = "LONG",
    entry: str = "67450",
    sl: str = "66800",
    tp: str = "69200",
    leverage: int = 5,
) -> RawSignal:
    return RawSignal(
        direction=direction,
        coin="BTC",
        symbol="BTCUSDT",
        confidence=0.87,
        entry_price=Decimal(entry),
        take_profit=Decimal(tp),
        stop_loss=Decimal(sl),
        leverage=leverage,
    )


def _account(
    balance: str = "10000",
    available: str = "10000",
) -> AccountState:
    return AccountState(
        available_balance=Decimal(available),
        total_balance=Decimal(balance),
        initial_balance=Decimal(balance),
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )


def _stats(
    total: int = 42,
    wins: int = 28,
    avg_win: str = "250.00",
    avg_loss: str = "100.00",
) -> TradeStatistics:
    gross_win = Decimal(avg_win) * wins
    gross_loss = Decimal(avg_loss) * (total - wins)
    return TradeStatistics(
        total_trades=total,
        winning_trades=wins,
        losing_trades=total - wins,
        total_pnl=gross_win - gross_loss,
        avg_win_usdt=Decimal(avg_win),
        avg_loss_usdt=Decimal(avg_loss),
        gross_win_usdt=gross_win,
        gross_loss_usdt=gross_loss,
    )


@pytest.fixture
def engine() -> PositionSizingEngine:
    return PositionSizingEngine()


# ════════════════════════════════════════════════════════════════
# Fixed Risk 테스트
# ════════════════════════════════════════════════════════════════

class TestFixedRisk:
    def test_risk_amount_equals_balance_times_pct(self, engine: PositionSizingEngine) -> None:
        """risk_amount = balance × risk_pct"""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        # balance=10000, pct=2% → risk=200
        assert result.max_loss == Decimal("200.00")

    def test_example_from_trading_rules(self, engine: PositionSizingEngine) -> None:
        """
        TRADING_RULES.md §7.1 공식 검증:
        balance=10000, risk=2%, entry=67450, sl=66800, lev=5x
        → sl_distance=650, risk_amount=200
        → margin=200/650=0.3077, qty=(0.3077×5)/67450≈0.022 BTC
        """
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        assert result.quantity == Decimal("0.022")
        assert result.max_loss == Decimal("200.00")
        assert result.final_leverage == 5
        assert result.method == SizingMethod.FIXED_RISK

    def test_risk_pct_clamped_to_max(self, engine: PositionSizingEngine) -> None:
        """6%는 max 5%로 클리핑."""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.06)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        assert result.risk_pct <= 0.05 + 1e-9

    def test_risk_pct_clamped_to_min(self, engine: PositionSizingEngine) -> None:
        """0.1%는 min 0.5%로 클리핑."""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.001)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        assert result.risk_pct >= 0.005 - 1e-9

    def test_no_stop_loss_raises(self, engine: PositionSizingEngine) -> None:
        signal_no_sl = _signal()
        signal_no_sl.stop_loss = None  # type: ignore[assignment]
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)

        with pytest.raises(ValueError, match="stop_loss"):
            engine.calculate(config, signal_no_sl, _account(), 5, "BTCUSDT")

    def test_larger_balance_larger_position(self, engine: PositionSizingEngine) -> None:
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        small = engine.calculate(config, _signal(), _account("5000"), 5, "BTCUSDT")
        large = engine.calculate(config, _signal(), _account("20000"), 5, "BTCUSDT")

        assert large.quantity > small.quantity
        assert large.max_loss == small.max_loss * 2


# ════════════════════════════════════════════════════════════════
# Fixed Dollar 테스트
# ════════════════════════════════════════════════════════════════

class TestFixedDollar:
    def test_fixed_dollar_ignores_balance(self, engine: PositionSizingEngine) -> None:
        """Fixed Dollar: balance와 관계없이 고정 금액 사용."""
        config = SizingConfig(method=SizingMethod.FIXED_DOLLAR, risk_usdt=Decimal("200"))
        small_bal = engine.calculate(config, _signal(), _account("5000"), 5, "BTCUSDT")
        large_bal = engine.calculate(config, _signal(), _account("50000"), 5, "BTCUSDT")

        # 같은 risk_usdt → 같은 risk_amount
        assert small_bal.max_loss == large_bal.max_loss

    def test_fixed_dollar_capped_by_max_pct(self, engine: PositionSizingEngine) -> None:
        """고정 금액이 5% 상한 초과 시 클리핑."""
        # balance=1000, max_risk=5%=50, risk_usdt=200 → 클리핑 → 50
        config = SizingConfig(method=SizingMethod.FIXED_DOLLAR, risk_usdt=Decimal("200"))
        result = engine.calculate(config, _signal(), _account("1000"), 5, "BTCUSDT")

        assert result.max_loss <= Decimal("50.01")  # 5% of 1000
        assert any("상한" in w for w in result.warnings)

    def test_fixed_dollar_fallback_when_none(self, engine: PositionSizingEngine) -> None:
        """risk_usdt=None이면 1% 기본값 사용."""
        config = SizingConfig(method=SizingMethod.FIXED_DOLLAR, risk_usdt=None)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        assert result.max_loss == Decimal("100.00")  # 1% of 10000
        assert any("미설정" in w for w in result.warnings)


# ════════════════════════════════════════════════════════════════
# Percent Risk 테스트
# ════════════════════════════════════════════════════════════════

class TestPercentRisk:
    def test_uses_available_balance(self, engine: PositionSizingEngine) -> None:
        """Percent Risk: 가용 잔고 기준 (총 잔고 아님)."""
        config = SizingConfig(method=SizingMethod.PERCENT_RISK, risk_pct=0.02)
        result = engine.calculate(
            config, _signal(),
            _account(balance="10000", available="8000"),   # 2000 증거금 사용 중
            5, "BTCUSDT",
        )
        # 2% of available 8000 = 160
        assert result.max_loss == Decimal("160.00")

    def test_vs_fixed_risk_with_full_balance(self, engine: PositionSizingEngine) -> None:
        """가용 잔고 = 총 잔고이면 Fixed Risk와 동일."""
        config_fr = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        config_pr = SizingConfig(method=SizingMethod.PERCENT_RISK, risk_pct=0.02)
        account = _account("10000", "10000")

        result_fr = engine.calculate(config_fr, _signal(), account, 5, "BTCUSDT")
        result_pr = engine.calculate(config_pr, _signal(), account, 5, "BTCUSDT")

        assert result_fr.quantity == result_pr.quantity
        assert result_fr.max_loss == result_pr.max_loss

    def test_percent_risk_different_when_margin_used(self, engine: PositionSizingEngine) -> None:
        """가용 잔고 < 총 잔고이면 Fixed Risk와 결과 다름."""
        account_partial = _account("10000", "7000")   # 3000 증거금 사용 중
        config_fr = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        config_pr = SizingConfig(method=SizingMethod.PERCENT_RISK, risk_pct=0.02)

        result_fr = engine.calculate(config_fr, _signal(), account_partial, 5, "BTCUSDT")
        result_pr = engine.calculate(config_pr, _signal(), account_partial, 5, "BTCUSDT")

        # Fixed Risk: 2% × 10000 = 200
        # Percent Risk: 2% × 7000 = 140
        assert result_fr.max_loss > result_pr.max_loss


# ════════════════════════════════════════════════════════════════
# Kelly Criterion 테스트
# ════════════════════════════════════════════════════════════════

class TestKellyCriterion:
    def test_kelly_with_good_stats(self, engine: PositionSizingEngine) -> None:
        """좋은 거래 이력 → Kelly 유효, risk_pct 계산됨."""
        config = SizingConfig(method=SizingMethod.KELLY, kelly_fraction=0.25)
        stats = _stats(total=42, wins=28, avg_win="250", avg_loss="100")

        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT", stats)

        assert result.method == SizingMethod.KELLY
        assert result.kelly is not None
        assert result.kelly.is_valid is True
        assert result.max_loss > 0

    def test_kelly_fallback_insufficient_data(self, engine: PositionSizingEngine) -> None:
        """샘플 부족 → fallback 리스크 적용."""
        config = SizingConfig(
            method=SizingMethod.KELLY,
            kelly_fraction=0.25,
            kelly_min_trades=20,
            kelly_fallback_risk_pct=0.01,
        )
        few_trades = _stats(total=5, wins=3, avg_win="200", avg_loss="100")  # 5 < 20

        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT", few_trades)

        assert result.kelly is not None
        assert result.kelly.is_valid is False
        # fallback 1% of 10000 = 100
        assert abs(result.max_loss - Decimal("100.00")) < Decimal("1.00")

    def test_kelly_fallback_no_history(self, engine: PositionSizingEngine) -> None:
        """거래 이력 없음 → fallback."""
        config = SizingConfig(method=SizingMethod.KELLY, kelly_fallback_risk_pct=0.01)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT", None)

        assert result.kelly is not None
        assert result.kelly.is_valid is False

    def test_kelly_capped_at_max_risk_pct(self, engine: PositionSizingEngine) -> None:
        """Kelly가 5% 상한 초과 시 클리핑."""
        config = SizingConfig(method=SizingMethod.KELLY, kelly_fraction=1.0, max_risk_pct=0.05)
        # 극도로 높은 승률 + 높은 odds → Full Kelly가 매우 클 수 있음
        high_perf = _stats(total=100, wins=80, avg_win="500", avg_loss="100")

        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT", high_perf)

        # 상한 5%이므로 max_loss <= 500
        assert result.max_loss <= Decimal("500.01")

    def test_kelly_negative_expected_value(self, engine: PositionSizingEngine) -> None:
        """기대값 음수 → Kelly 음수 → fallback."""
        config = SizingConfig(
            method=SizingMethod.KELLY,
            kelly_fraction=0.25,
            kelly_fallback_risk_pct=0.01,
        )
        # 낮은 승률 + 낮은 odds → Kelly < 0
        bad_stats = _stats(total=50, wins=10, avg_win="50", avg_loss="200")

        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT", bad_stats)

        assert result.kelly is not None
        assert result.kelly.is_valid is False
        assert "음수" in (result.kelly.reason or "")


# ════════════════════════════════════════════════════════════════
# 방법 비교 테스트
# ════════════════════════════════════════════════════════════════

class TestCompareAll:
    def test_compare_returns_all_4_methods(self, engine: PositionSizingEngine) -> None:
        stats = _stats()
        comparison = engine.compare_all(
            signal=_signal(),
            account=_account("10000"),
            leverage=5,
            symbol="BTCUSDT",
            base_risk_pct=0.02,
            trade_stats=stats,
        )

        assert "fixed_risk"   in comparison.results
        assert "fixed_dollar" in comparison.results
        assert "percent_risk" in comparison.results
        assert "kelly"        in comparison.results

    def test_compare_methods_have_quantities(self, engine: PositionSizingEngine) -> None:
        comparison = engine.compare_all(
            signal=_signal(),
            account=_account("10000"),
            leverage=5,
            symbol="BTCUSDT",
            base_risk_pct=0.02,
        )
        for method, result in comparison.results.items():
            assert "quantity" in result, f"{method} missing quantity"

    def test_fixed_risk_and_percent_risk_equal_full_balance(
        self, engine: PositionSizingEngine
    ) -> None:
        """가용 잔고 = 총 잔고이면 Fixed Risk ≈ Percent Risk."""
        account = _account("10000", "10000")
        comparison = engine.compare_all(
            signal=_signal(),
            account=account,
            leverage=5,
            symbol="BTCUSDT",
            base_risk_pct=0.02,
        )
        fr_qty = comparison.results["fixed_risk"]["quantity"]
        pr_qty = comparison.results["percent_risk"]["quantity"]
        assert fr_qty == pr_qty


# ════════════════════════════════════════════════════════════════
# 공통 검증 테스트
# ════════════════════════════════════════════════════════════════

class TestCommonValidation:
    def test_higher_leverage_more_quantity(self, engine: PositionSizingEngine) -> None:
        """레버리지 높을수록 동일 리스크로 더 많은 수량."""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        low_lev = engine.calculate(config, _signal(leverage=3), _account("10000"), 3, "BTCUSDT")
        high_lev = engine.calculate(config, _signal(leverage=10), _account("10000"), 10, "BTCUSDT")

        assert high_lev.quantity > low_lev.quantity
        # 하지만 max_loss는 동일 (리스크 금액은 레버리지 무관)
        assert high_lev.max_loss == low_lev.max_loss

    def test_wider_sl_smaller_quantity(self, engine: PositionSizingEngine) -> None:
        """SL이 넓을수록 같은 리스크 금액으로 적은 수량."""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        tight_sl = engine.calculate(config, _signal(sl="67250"), _account("10000"), 5, "BTCUSDT")
        wide_sl = engine.calculate(config, _signal(sl="65000"), _account("10000"), 5, "BTCUSDT")

        assert wide_sl.quantity < tight_sl.quantity

    def test_rr_ratio_calculated_correctly(self, engine: PositionSizingEngine) -> None:
        """R:R 비율 정확성 — entry=67450, sl=66800, tp=69200."""
        # LONG: profit=69200-67450=1750, loss=67450-66800=650, R:R=1750/650≈2.69
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        assert float(result.rr_ratio) == pytest.approx(2.69, rel=0.01)

    def test_result_to_dict_structure(self, engine: PositionSizingEngine) -> None:
        """to_dict() 반환값 구조 검증."""
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")
        d = result.to_dict()

        required_keys = [
            "method", "risk_amount_usdt", "risk_pct",
            "quantity", "margin_used", "position_value",
            "max_loss", "max_profit", "final_leverage", "rr_ratio",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_validate_sufficient_balance(self, engine: PositionSizingEngine) -> None:
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        ok, reason = engine.validate(
            result,
            available_balance=Decimal("10000"),
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is True

    def test_validate_insufficient_balance(self, engine: PositionSizingEngine) -> None:
        config = SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=0.02)
        result = engine.calculate(config, _signal(), _account("10000"), 5, "BTCUSDT")

        ok, reason = engine.validate(
            result,
            available_balance=Decimal("100"),   # 훨씬 적은 잔고
            entry_price=Decimal("67450"),
            symbol="BTCUSDT",
        )
        assert ok is False
