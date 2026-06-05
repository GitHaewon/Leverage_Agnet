"""
백테스트 성과 지표 단위 테스트 — 6종 핵심 지표 수학적 정확성.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.backtest.metrics import (
    calc_cagr,
    calc_calmar_ratio,
    calc_max_drawdown,
    calc_profit_factor,
    calc_sharpe_ratio,
    calc_sortino_ratio,
    calc_total_return,
    calc_win_rate,
    build_equity_curve_with_drawdown,
)
from agents.backtest.models import BacktestConfig, EquityPoint, Trade, TradeExitReason


def _eq_point(ts: str, equity: str) -> EquityPoint:
    return EquityPoint(
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc),
        equity=Decimal(equity),
        cash=Decimal(equity),
        unrealized_pnl=Decimal("0"),
        open_positions=0,
        peak_equity=Decimal("0"),
        drawdown_pct=0.0,
    )


def _closed_trade(net_pnl: str, margin: str = "200") -> Trade:
    t = Trade(
        trade_id="t1", signal_id="s1", symbol="BTCUSDT",
        direction="LONG",
        entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        signal_entry_price=Decimal("67450"),
        actual_entry_price=Decimal("67450"),
        quantity=Decimal("0.01"),
        leverage=5,
        margin_used=Decimal(margin),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66800"),
    )
    t.exit_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t.actual_exit_price = Decimal("68000")
    t.exit_reason = TradeExitReason.TAKE_PROFIT
    t.gross_pnl = Decimal(net_pnl)
    t.net_pnl   = Decimal(net_pnl)
    return t


# ════════════════════════════════════════════════════════════════
# Total Return
# ════════════════════════════════════════════════════════════════

class TestTotalReturn:
    def test_profit(self) -> None:
        assert calc_total_return(Decimal("10000"), Decimal("12000")) == pytest.approx(20.0)

    def test_loss(self) -> None:
        assert calc_total_return(Decimal("10000"), Decimal("8000")) == pytest.approx(-20.0)

    def test_breakeven(self) -> None:
        assert calc_total_return(Decimal("10000"), Decimal("10000")) == pytest.approx(0.0)

    def test_zero_initial(self) -> None:
        assert calc_total_return(Decimal("0"), Decimal("1000")) == 0.0


# ════════════════════════════════════════════════════════════════
# CAGR
# ════════════════════════════════════════════════════════════════

class TestCAGR:
    def test_one_year_doubling(self) -> None:
        """1년에 2배 → CAGR = 100%."""
        cagr = calc_cagr(Decimal("10000"), Decimal("20000"), 365)
        assert cagr == pytest.approx(100.0, rel=0.01)

    def test_two_year_quadrupling(self) -> None:
        """2년에 4배 → CAGR = 100% (2년 기준)."""
        cagr = calc_cagr(Decimal("10000"), Decimal("40000"), 730)
        assert cagr == pytest.approx(100.0, rel=0.01)

    def test_loss_is_negative(self) -> None:
        cagr = calc_cagr(Decimal("10000"), Decimal("5000"), 365)
        assert cagr < 0

    def test_short_period(self) -> None:
        """30일에 10% → CAGR > 10%."""
        cagr = calc_cagr(Decimal("10000"), Decimal("11000"), 30)
        assert cagr > 10.0

    def test_zero_initial_returns_zero(self) -> None:
        assert calc_cagr(Decimal("0"), Decimal("10000"), 365) == 0.0


# ════════════════════════════════════════════════════════════════
# Max Drawdown
# ════════════════════════════════════════════════════════════════

class TestMaxDrawdown:
    def test_simple_drawdown(self) -> None:
        """10000 → 8000 → 회복 → MDD = -20%."""
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "8000"),   # -20%
            _eq_point("2026-01-03", "11000"),   # 회복
        ]
        mdd = calc_max_drawdown(curve)
        assert mdd == pytest.approx(-20.0, abs=0.1)

    def test_monotonic_increase_zero_mdd(self) -> None:
        """단조 증가 → MDD = 0%."""
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "11000"),
            _eq_point("2026-01-03", "12000"),
        ]
        mdd = calc_max_drawdown(curve)
        assert mdd == 0.0

    def test_multiple_drawdowns_takes_max(self) -> None:
        """여러 낙폭 중 최대값 선택."""
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "9500"),   # -5%
            _eq_point("2026-01-03", "10000"),
            _eq_point("2026-01-04", "7000"),   # -30% from peak
            _eq_point("2026-01-05", "10000"),
        ]
        mdd = calc_max_drawdown(curve)
        assert mdd == pytest.approx(-30.0, abs=0.1)

    def test_mdd_is_negative(self) -> None:
        """MDD는 항상 음수(또는 0)."""
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "9000"),
        ]
        assert calc_max_drawdown(curve) <= 0.0

    def test_empty_curve_returns_zero(self) -> None:
        assert calc_max_drawdown([]) == 0.0


# ════════════════════════════════════════════════════════════════
# Sharpe Ratio
# ════════════════════════════════════════════════════════════════

class TestSharpeRatio:
    def test_positive_sharpe_good_performance(self) -> None:
        """꾸준한 상승 → 양수 Sharpe."""
        curve = [
            _eq_point(f"2026-01-{d:02d}", str(10000 + d * 50))
            for d in range(1, 31)
        ]
        sharpe = calc_sharpe_ratio(curve, risk_free_rate=0.04)
        assert sharpe > 0

    def test_negative_sharpe_losses(self) -> None:
        """꾸준한 하락 → 음수 Sharpe."""
        curve = [
            _eq_point(f"2026-01-{d:02d}", str(10000 - d * 50))
            for d in range(1, 31)
        ]
        sharpe = calc_sharpe_ratio(curve, risk_free_rate=0.04)
        assert sharpe < 0

    def test_zero_variance_returns_zero(self) -> None:
        """변동 없음 → std=0 → 0 반환."""
        curve = [_eq_point(f"2026-01-{d:02d}", "10000") for d in range(1, 10)]
        sharpe = calc_sharpe_ratio(curve)
        assert sharpe == 0.0

    def test_insufficient_data_returns_zero(self) -> None:
        curve = [_eq_point("2026-01-01", "10000")]
        assert calc_sharpe_ratio(curve) == 0.0


# ════════════════════════════════════════════════════════════════
# Profit Factor
# ════════════════════════════════════════════════════════════════

class TestProfitFactor:
    def test_textbook_example(self) -> None:
        """총 수익 $300, 총 손실 $100 → Profit Factor = 3.0."""
        trades = [
            _closed_trade("150"),
            _closed_trade("150"),
            _closed_trade("-50"),
            _closed_trade("-50"),
        ]
        pf = calc_profit_factor(trades)
        assert pf == pytest.approx(3.0, rel=0.01)

    def test_no_losses_returns_inf(self) -> None:
        trades = [_closed_trade("100"), _closed_trade("200")]
        assert calc_profit_factor(trades) == float("inf")

    def test_only_losses_returns_zero(self) -> None:
        trades = [_closed_trade("-100"), _closed_trade("-200")]
        assert calc_profit_factor(trades) == pytest.approx(0.0)

    def test_empty_trades_returns_1(self) -> None:
        assert calc_profit_factor([]) == 1.0

    def test_above_1_means_profitable(self) -> None:
        trades = [_closed_trade("200"), _closed_trade("-100")]
        assert calc_profit_factor(trades) > 1.0


# ════════════════════════════════════════════════════════════════
# Win Rate
# ════════════════════════════════════════════════════════════════

class TestWinRate:
    def test_60pct_win_rate(self) -> None:
        trades = [
            _closed_trade("100"),
            _closed_trade("100"),
            _closed_trade("100"),
            _closed_trade("-50"),
            _closed_trade("-50"),
        ]
        assert calc_win_rate(trades) == pytest.approx(0.60)

    def test_all_winners(self) -> None:
        assert calc_win_rate([_closed_trade("100"), _closed_trade("200")]) == 1.0

    def test_all_losers(self) -> None:
        assert calc_win_rate([_closed_trade("-100"), _closed_trade("-200")]) == 0.0

    def test_empty_returns_zero(self) -> None:
        assert calc_win_rate([]) == 0.0


# ════════════════════════════════════════════════════════════════
# Calmar Ratio
# ════════════════════════════════════════════════════════════════

class TestCalmarRatio:
    def test_calmar_20_cagr_10_mdd(self) -> None:
        """CAGR=20%, MDD=-10% → Calmar=2.0."""
        assert calc_calmar_ratio(20.0, -10.0) == pytest.approx(2.0)

    def test_zero_mdd_returns_zero(self) -> None:
        assert calc_calmar_ratio(20.0, 0.0) == 0.0

    def test_negative_cagr(self) -> None:
        calmar = calc_calmar_ratio(-10.0, -20.0)
        assert calmar == pytest.approx(-0.5)


# ════════════════════════════════════════════════════════════════
# Equity Curve with Drawdown
# ════════════════════════════════════════════════════════════════

class TestEquityCurveWithDrawdown:
    def test_drawdown_filled_correctly(self) -> None:
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "9000"),   # -10%
            _eq_point("2026-01-03", "9500"),
        ]
        result = build_equity_curve_with_drawdown(curve)

        assert result[0].drawdown_pct == pytest.approx(0.0)
        assert result[1].drawdown_pct == pytest.approx(-10.0, abs=0.1)
        assert result[2].drawdown_pct < 0

    def test_peak_equity_tracks_maximum(self) -> None:
        curve = [
            _eq_point("2026-01-01", "10000"),
            _eq_point("2026-01-02", "11000"),  # 새 피크
            _eq_point("2026-01-03", "10000"),  # 하락
        ]
        result = build_equity_curve_with_drawdown(curve)

        assert float(result[2].peak_equity) == pytest.approx(11000.0)
