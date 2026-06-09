"""
Walk Forward Testing Engine — 성과 지표 계산.

지표:
  - CAGR  (Compound Annual Growth Rate)
  - Sharpe Ratio (연환산, 거래별 equity curve 기반)
  - MDD   (Maximum Drawdown)
  - Profit Factor (총 수익 / 총 손실)
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from .types import PerformanceMetrics, Trade, WalkForwardConfig


def calculate_cagr(
    initial_equity: float,
    final_equity: float,
    start_dt: datetime,
    end_dt: datetime,
) -> float:
    """
    CAGR = (final / initial)^(1 / years) - 1
    """
    days = (end_dt - start_dt).days
    if days <= 0 or initial_equity <= 0 or final_equity <= 0:
        return 0.0
    years = days / 365.25
    if years < 1 / 365.25:
        return 0.0
    return (final_equity / initial_equity) ** (1.0 / years) - 1.0


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """
    MDD = (trough - peak) / peak
    음수 반환 (-0.20 = -20%).
    """
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (arr - peak) / peak, 0.0)
    return float(dd.min())


def calculate_sharpe(
    equity_curve: list[float],
    risk_free_rate: float = 0.05,
) -> float:
    """
    연환산 Sharpe Ratio.

    거래 간 수익률을 사용하고 sqrt(252)로 연환산.
    거래 빈도가 일정하지 않아 엄밀한 일별 환산은 불가하지만,
    WFT의 상대적 비교 목적에 충분하다.
    """
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    returns = np.diff(arr) / np.where(arr[:-1] != 0, arr[:-1], 1.0)
    if len(returns) == 0:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std == 0.0:
        return 0.0
    rf_per_trade = risk_free_rate / 252
    excess = returns - rf_per_trade
    return float(np.mean(excess) / std * math.sqrt(252))


def calculate_profit_factor(trades: list[Trade]) -> float:
    """
    Profit Factor = 총 수익 / |총 손실|

    모두 이익이면 inf, 모두 손실이면 0 반환.
    """
    if not trades:
        return 0.0
    gross_profit = sum(t.pnl_usdt for t in trades if t.pnl_usdt > 0)
    gross_loss = abs(sum(t.pnl_usdt for t in trades if t.pnl_usdt < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calculate_metrics(
    trades: list[Trade],
    equity_curve: list[float],
    config: WalkForwardConfig,
    start_dt: datetime,
    end_dt: datetime,
) -> PerformanceMetrics:
    """
    trades + equity_curve → PerformanceMetrics 전체 계산.
    """
    if not trades or len(equity_curve) < 2:
        return PerformanceMetrics.empty()

    initial = equity_curve[0]
    final = equity_curve[-1]

    cagr = calculate_cagr(initial, final, start_dt, end_dt)
    sharpe = calculate_sharpe(equity_curve, config.risk_free_rate)
    mdd = calculate_max_drawdown(equity_curve)
    pf = calculate_profit_factor(trades)

    wins = [t for t in trades if t.pnl_usdt > 0]
    pnls = [t.pnl_usdt for t in trades]

    # Calmar: 손실이 없으면(mdd==0) 0으로 처리
    calmar = (cagr / abs(mdd)) if mdd < 0 else 0.0

    return PerformanceMetrics(
        cagr=cagr,
        sharpe_ratio=sharpe,
        max_drawdown=mdd,
        profit_factor=pf,
        win_rate=len(wins) / len(trades),
        total_trades=len(trades),
        total_pnl_usdt=sum(pnls),
        avg_pnl_usdt=sum(pnls) / len(pnls),
        calmar_ratio=calmar,
        best_trade_usdt=max(pnls),
        worst_trade_usdt=min(pnls),
        final_equity=final,
    )
