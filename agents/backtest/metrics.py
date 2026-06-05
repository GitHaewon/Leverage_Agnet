"""
백테스트 성과 지표 계산기.

6종 핵심 지표:
  1. Total Return   — 총 수익률
  2. CAGR           — 연환산 수익률
  3. Max Drawdown   — 최대 낙폭
  4. Sharpe Ratio   — 위험 조정 수익률
  5. Profit Factor  — 총 수익 / 총 손실
  6. Win Rate       — 승률

보조 지표:
  - Sortino Ratio   — 하방 위험 기반 Sharpe
  - Calmar Ratio    — CAGR / |MDD|
  - Expectancy      — 거래당 기대 수익
  - Cost Drag       — 비용이 수익에 미친 영향
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from agents.backtest.models import BacktestConfig, BacktestMetrics, EquityPoint, Trade


# ════════════════════════════════════════════════════════════════
# 개별 지표 계산 함수 (순수 함수 — 독립 테스트 가능)
# ════════════════════════════════════════════════════════════════

def calc_total_return(initial: Decimal, final: Decimal) -> float:
    """총 수익률 (%)."""
    if initial == 0:
        return 0.0
    return float((final - initial) / initial * 100)


def calc_cagr(
    initial: Decimal,
    final: Decimal,
    duration_days: int,
    periods_per_year: int = 365,
) -> float:
    """
    연환산 수익률 (CAGR, %).

    CAGR = (final / initial)^(periods_per_year / duration_days) - 1
    """
    if initial <= 0 or duration_days <= 0:
        return 0.0
    ratio = float(final / initial)
    if ratio <= 0:
        return -100.0
    exponent = periods_per_year / duration_days
    return (ratio ** exponent - 1) * 100


def calc_max_drawdown(equity_curve: Sequence[EquityPoint]) -> float:
    """
    최대 낙폭 (MDD, %).

    Peak-to-Trough: (trough - peak) / peak × 100

    Returns: 음수 (예: -15.3)
    """
    if not equity_curve:
        return 0.0

    peak = float(equity_curve[0].equity)
    max_dd = 0.0

    for point in equity_curve:
        val = float(point.equity)
        if val > peak:
            peak = val
        if peak > 0:
            dd = (val - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

    return max_dd


def calc_sharpe_ratio(
    equity_curve: Sequence[EquityPoint],
    risk_free_rate: float = 0.04,
    periods_per_year: int = 365,
) -> float:
    """
    Sharpe Ratio.

    Sharpe = (avg_daily_return - risk_free_daily) / std(daily_returns) × √periods

    risk_free_daily = (1 + risk_free_rate)^(1/365) - 1
    """
    if len(equity_curve) < 2:
        return 0.0

    equities = [float(p.equity) for p in equity_curve]
    daily_returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]

    if len(daily_returns) < 2:
        return 0.0

    avg_return = statistics.mean(daily_returns)
    std_return = statistics.stdev(daily_returns)

    if std_return == 0:
        return 0.0

    # 일별 무위험 수익률
    risk_free_daily = (1 + risk_free_rate) ** (1 / 365) - 1
    excess = avg_return - risk_free_daily

    return (excess / std_return) * math.sqrt(periods_per_year)


def calc_sortino_ratio(
    equity_curve: Sequence[EquityPoint],
    risk_free_rate: float = 0.04,
    periods_per_year: int = 365,
) -> float:
    """
    Sortino Ratio — 하방 변동성만 사용.

    Sortino = (avg_return - risk_free) / downside_deviation × √periods
    downside_deviation = std(음수 수익률만)
    """
    if len(equity_curve) < 2:
        return 0.0

    equities = [float(p.equity) for p in equity_curve]
    daily_returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]

    if not daily_returns:
        return 0.0

    risk_free_daily = (1 + risk_free_rate) ** (1 / 365) - 1
    avg_return = statistics.mean(daily_returns)
    excess = avg_return - risk_free_daily

    downside = [r for r in daily_returns if r < risk_free_daily]
    if len(downside) < 2:
        return 0.0

    downside_std = statistics.stdev(downside)
    if downside_std == 0:
        return 0.0

    return (excess / downside_std) * math.sqrt(periods_per_year)


def calc_calmar_ratio(cagr: float, mdd: float) -> float:
    """
    Calmar Ratio = CAGR / |MDD|.
    MDD가 0이면 0 반환.
    """
    if mdd == 0:
        return 0.0
    return cagr / abs(mdd)


def calc_profit_factor(trades: Sequence[Trade]) -> float:
    """
    Profit Factor = 총 수익 / 총 손실 절댓값.
    손실 거래가 없으면 inf 반환.
    """
    closed = [t for t in trades if t.net_pnl is not None]
    gross_win = sum(float(t.net_pnl) for t in closed if t.net_pnl > 0)
    gross_loss = sum(abs(float(t.net_pnl)) for t in closed if t.net_pnl < 0)

    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 1.0
    return gross_win / gross_loss


def calc_win_rate(trades: Sequence[Trade]) -> float:
    """승률 (0.0 ~ 1.0)."""
    closed = [t for t in trades if t.net_pnl is not None]
    if not closed:
        return 0.0
    winners = sum(1 for t in closed if t.net_pnl > 0)
    return winners / len(closed)


def calc_expectancy(trades: Sequence[Trade]) -> Decimal:
    """
    거래당 기대 수익 (Expectancy).
    E = win_rate × avg_win - loss_rate × avg_loss
    """
    closed = [t for t in trades if t.net_pnl is not None]
    if not closed:
        return Decimal("0")

    winners = [t.net_pnl for t in closed if t.net_pnl > 0]
    losers  = [abs(t.net_pnl) for t in closed if t.net_pnl < 0]

    win_rate  = len(winners) / len(closed)
    loss_rate = 1 - win_rate

    avg_win  = sum(winners, Decimal("0")) / len(winners) if winners else Decimal("0")
    avg_loss = sum(losers,  Decimal("0")) / len(losers)  if losers  else Decimal("0")

    return Decimal(str(win_rate)) * avg_win - Decimal(str(loss_rate)) * avg_loss


def calc_cost_drag(
    total_costs: Decimal,
    initial_capital: Decimal,
) -> float:
    """비용 드래그 — 비용이 수익률에 미친 영향 (%)."""
    if initial_capital == 0:
        return 0.0
    return float(total_costs / initial_capital * 100)


def build_equity_curve_with_drawdown(
    equity_points: list[EquityPoint],
) -> list[EquityPoint]:
    """낙폭과 피크 정보를 채워 equity curve 완성."""
    if not equity_points:
        return []

    peak = float(equity_points[0].equity)
    for point in equity_points:
        val = float(point.equity)
        if val > peak:
            peak = val
        point.peak_equity = Decimal(str(peak))
        point.drawdown_pct = (val - peak) / peak * 100 if peak > 0 else 0.0

    return equity_points


# ════════════════════════════════════════════════════════════════
# 통합 성과 지표 계산기
# ════════════════════════════════════════════════════════════════

class MetricsCalculator:
    """모든 성과 지표를 한번에 계산."""

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

    def calculate(
        self,
        trades: list[Trade],
        equity_curve: list[EquityPoint],
        start_date: datetime,
        end_date: datetime,
        initial_capital: Decimal,
        total_bars: int,
    ) -> BacktestMetrics:
        """BacktestMetrics 전체 계산."""
        closed = [t for t in trades if t.net_pnl is not None]
        final_equity = equity_curve[-1].equity if equity_curve else initial_capital

        duration_days = max(1, (end_date - start_date).days)

        # ── 핵심 6종 지표 ─────────────────────────────────────────────────
        total_return = calc_total_return(initial_capital, final_equity)
        cagr         = calc_cagr(initial_capital, final_equity, duration_days,
                                  self._config.periods_per_year)
        mdd          = calc_max_drawdown(equity_curve)
        sharpe       = calc_sharpe_ratio(equity_curve, self._config.risk_free_rate,
                                          self._config.periods_per_year)
        profit_factor = calc_profit_factor(closed)
        win_rate      = calc_win_rate(closed)

        # ── 보조 지표 ──────────────────────────────────────────────────────
        sortino = calc_sortino_ratio(equity_curve, self._config.risk_free_rate,
                                      self._config.periods_per_year)
        calmar  = calc_calmar_ratio(cagr, mdd)

        # ── 거래 통계 ──────────────────────────────────────────────────────
        winners = [t for t in closed if t.net_pnl > 0]
        losers  = [t for t in closed if t.net_pnl <= 0]

        avg_win = (
            sum((t.net_pnl for t in winners), Decimal("0")) / len(winners)
            if winners else Decimal("0")
        )
        avg_loss = (
            sum((abs(t.net_pnl) for t in losers), Decimal("0")) / len(losers)
            if losers else Decimal("0")
        )

        durations = [t.duration_hours for t in closed if t.duration_hours is not None]
        avg_duration = statistics.mean(durations) if durations else 0.0

        best  = max((t.net_pnl for t in closed), default=Decimal("0"))
        worst = min((t.net_pnl for t in closed), default=Decimal("0"))

        # ── 비용 집계 ──────────────────────────────────────────────────────
        total_fees         = sum((t.entry_fee + t.exit_fee for t in closed), Decimal("0"))
        total_slippage     = sum((t.slippage_cost for t in closed), Decimal("0"))
        total_funding_fees = sum((abs(t.funding_fees) for t in closed), Decimal("0"))
        total_costs        = total_fees + total_slippage + total_funding_fees
        cost_drag          = calc_cost_drag(total_costs, initial_capital)

        return BacktestMetrics(
            total_return=total_return,
            cagr=cagr,
            max_drawdown=mdd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            win_rate=win_rate,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            total_trades=len(closed),
            winning_trades=len(winners),
            losing_trades=len(losers),
            avg_win_usdt=avg_win.quantize(Decimal("0.01")),
            avg_loss_usdt=avg_loss.quantize(Decimal("0.01")),
            avg_trade_duration_hours=avg_duration,
            best_trade=best.quantize(Decimal("0.01")),
            worst_trade=worst.quantize(Decimal("0.01")),
            total_fees=total_fees.quantize(Decimal("0.01")),
            total_slippage=total_slippage.quantize(Decimal("0.01")),
            total_funding_fees=total_funding_fees.quantize(Decimal("0.01")),
            total_costs=total_costs.quantize(Decimal("0.01")),
            cost_drag_pct=cost_drag,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            total_bars=total_bars,
            initial_capital=initial_capital,
            final_equity=final_equity.quantize(Decimal("0.01")),
        )
