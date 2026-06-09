"""
성과 지표 단위 테스트 (20 tests).

검증 대상:
  - calculate_cagr:         복리 연수익률 계산
  - calculate_max_drawdown: 최대 낙폭 (음수)
  - calculate_sharpe:       연환산 Sharpe Ratio
  - calculate_profit_factor: 총 수익 / 총 손실
  - calculate_metrics:       통합 지표 계산
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtesting.metrics import (
    calculate_cagr,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe,
    calculate_metrics,
)
from app.backtesting.types import PerformanceMetrics, Trade, WalkForwardConfig

UTC = timezone.utc


def _make_trade(pnl: float, direction: str = "LONG") -> Trade:
    return Trade(
        entry_time=datetime(2025, 1, 1, tzinfo=UTC),
        exit_time=datetime(2025, 1, 2, tzinfo=UTC),
        direction=direction,
        entry_price=40_000.0,
        exit_price=41_000.0 if pnl > 0 else 39_000.0,
        quantity=0.01,
        leverage=5,
        margin_used=100.0,
        pnl_usdt=pnl,
        pnl_pct=pnl / 100.0,
        rr_ratio=2.0,
        close_reason="tp_hit" if pnl > 0 else "sl_hit",
        gross_pnl=pnl + 0.5,
        commission=0.5,
    )


# ── TestCagr ─────────────────────────────────────────────────────────────────

class TestCagr:
    def test_one_year_double(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        cagr = calculate_cagr(10_000.0, 20_000.0, start, end)
        assert abs(cagr - 1.0) < 0.01

    def test_zero_days_returns_zero(self) -> None:
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        assert calculate_cagr(10_000.0, 12_000.0, dt, dt) == 0.0

    def test_loss_scenario_negative_cagr(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        cagr = calculate_cagr(10_000.0, 8_000.0, start, end)
        assert cagr < 0.0

    def test_no_change_returns_zero(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        cagr = calculate_cagr(10_000.0, 10_000.0, start, end)
        assert abs(cagr) < 1e-9

    def test_two_year_quadruple(self) -> None:
        # (4)^(1/2) - 1 = 1.0 → 100% CAGR
        start = datetime(2023, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        cagr = calculate_cagr(10_000.0, 40_000.0, start, end)
        assert abs(cagr - 1.0) < 0.02


# ── TestMaxDrawdown ───────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_no_drawdown_monotone_rise(self) -> None:
        eq = [100.0, 110.0, 120.0, 130.0]
        assert calculate_max_drawdown(eq) == 0.0

    def test_single_20pct_dip(self) -> None:
        eq = [100.0, 80.0, 100.0]
        mdd = calculate_max_drawdown(eq)
        assert abs(mdd - (-0.20)) < 1e-9

    def test_multiple_dips_returns_worst(self) -> None:
        # peak=100, dip to 70 = -30%
        eq = [100.0, 90.0, 95.0, 70.0, 100.0]
        mdd = calculate_max_drawdown(eq)
        assert abs(mdd - (-0.30)) < 1e-9

    def test_single_point_returns_zero(self) -> None:
        assert calculate_max_drawdown([100.0]) == 0.0

    def test_total_loss(self) -> None:
        eq = [100.0, 50.0, 0.001]
        mdd = calculate_max_drawdown(eq)
        assert mdd < -0.99


# ── TestSharpe ────────────────────────────────────────────────────────────────

class TestSharpe:
    def test_consistently_rising_equity_positive_sharpe(self) -> None:
        eq = [100.0 + i * 5 for i in range(20)]
        sharpe = calculate_sharpe(eq, risk_free_rate=0.0)
        assert sharpe > 0.0

    def test_flat_equity_curve_returns_zero(self) -> None:
        eq = [100.0] * 10
        assert calculate_sharpe(eq) == 0.0

    def test_single_point_returns_zero(self) -> None:
        assert calculate_sharpe([100.0]) == 0.0

    def test_declining_equity_negative_sharpe(self) -> None:
        eq = [100.0 - i * 3 for i in range(10)]
        sharpe = calculate_sharpe(eq, risk_free_rate=0.0)
        assert sharpe < 0.0


# ── TestProfitFactor ──────────────────────────────────────────────────────────

class TestProfitFactor:
    def test_all_wins_returns_inf(self) -> None:
        trades = [_make_trade(100.0), _make_trade(50.0)]
        pf = calculate_profit_factor(trades)
        assert pf == float("inf")

    def test_all_losses_returns_zero(self) -> None:
        trades = [_make_trade(-100.0), _make_trade(-50.0)]
        assert calculate_profit_factor(trades) == 0.0

    def test_equal_profit_and_loss(self) -> None:
        trades = [_make_trade(100.0), _make_trade(-100.0)]
        assert abs(calculate_profit_factor(trades) - 1.0) < 1e-9

    def test_two_to_one_ratio(self) -> None:
        trades = [_make_trade(200.0), _make_trade(-100.0)]
        assert abs(calculate_profit_factor(trades) - 2.0) < 1e-9

    def test_empty_trades_returns_zero(self) -> None:
        assert calculate_profit_factor([]) == 0.0


# ── TestCalculateMetrics ──────────────────────────────────────────────────────

class TestCalculateMetrics:
    def _config(self) -> WalkForwardConfig:
        return WalkForwardConfig(initial_capital=10_000.0)

    def test_empty_trades_returns_empty_metrics(self) -> None:
        m = calculate_metrics(
            [],
            [10_000.0],
            self._config(),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert isinstance(m, PerformanceMetrics)
        assert m.total_trades == 0

    def test_winning_trades_positive_metrics(self) -> None:
        trades = [_make_trade(500.0) for _ in range(5)]
        equity = [10_000.0 + i * 500.0 for i in range(6)]
        m = calculate_metrics(
            trades, equity, self._config(),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert m.cagr > 0.0
        assert m.win_rate == 1.0
        assert m.total_trades == 5

    def test_calmar_ratio_negative_mdd(self) -> None:
        trades = [_make_trade(100.0) for _ in range(3)] + [_make_trade(-300.0)]
        # peak=10300, trough=10000 → MDD ≈ -2.9%
        equity = [10_000.0, 10_100.0, 10_200.0, 10_300.0, 10_000.0]
        m = calculate_metrics(
            trades, equity, self._config(),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert isinstance(m.calmar_ratio, float)

    def test_total_pnl_sum_matches(self) -> None:
        pnls = [100.0, -50.0, 200.0, -80.0]
        trades = [_make_trade(p) for p in pnls]
        equity = [10_000.0] + [10_000.0 + sum(pnls[:i+1]) for i in range(len(pnls))]
        m = calculate_metrics(
            trades, equity, self._config(),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert abs(m.total_pnl_usdt - sum(pnls)) < 1e-6

    def test_final_equity_matches_last_point(self) -> None:
        trades = [_make_trade(500.0)]
        equity = [10_000.0, 10_500.0]
        m = calculate_metrics(
            trades, equity, self._config(),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert abs(m.final_equity - 10_500.0) < 1e-9
