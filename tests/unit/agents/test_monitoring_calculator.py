"""
Monitoring 계산 함수 테스트.

검증:
  [order_success_rate]
  - 빈 목록 → 0
  - 전부 filled → 1.0
  - 전부 failed → 0.0
  - 혼합 (3/5 filled) → 0.6

  [win_rate]
  - 빈 목록 → 0
  - 전부 수익 → 1.0
  - 전부 손실 → 0.0
  - 혼합 (2/4 수익) → 0.5
  - PnL=0 거래 → 손실로 계산 (> 0 기준)

  [max_drawdown]
  - 데이터 0개 → 0
  - 데이터 1개 → 0
  - 단조 증가 시리즈 → 0 (낙폭 없음)
  - 단조 감소 시리즈 → (첫값 - 끝값) / 첫값
  - 고점 후 회복 → 중간 낙폭이 최대
  - 복수 낙폭 → 최대값 반환

  [daily_pnl]
  - 오늘 거래 없음 + 오픈 포지션 없음 → 0
  - 오늘 realized만 → 합계
  - 어제 거래는 제외
  - unrealized만 → 합계
  - realized + unrealized 합산

  [open_positions_count]
  - 빈 목록 → 0
  - N개 → N
"""
from __future__ import annotations

from decimal import Decimal

from agents.monitoring.calculator import (
    daily_pnl,
    max_drawdown,
    open_positions_count,
    order_success_rate,
    win_rate,
)

from tests.unit.agents._monitoring_fixtures import (
    make_balance_history,
    make_orders,
    make_position,
    make_trade,
    make_trades,
    today,
)


# ── order_success_rate ────────────────────────────────────────────────────────────

def test_order_success_rate_empty_returns_zero():
    assert order_success_rate([]) == Decimal("0")


def test_order_success_rate_all_filled():
    orders = make_orders(["filled", "filled", "filled"])
    assert order_success_rate(orders) == Decimal("1")


def test_order_success_rate_all_failed():
    orders = make_orders(["failed", "failed"])
    assert order_success_rate(orders) == Decimal("0")


def test_order_success_rate_mixed():
    """3/5 filled → 0.6."""
    orders = make_orders(["filled", "filled", "filled", "failed", "cancelled"])
    result = order_success_rate(orders)
    assert result == Decimal("3") / Decimal("5")


def test_order_success_rate_single_filled():
    orders = make_orders(["filled"])
    assert order_success_rate(orders) == Decimal("1")


def test_order_success_rate_single_failed():
    orders = make_orders(["failed"])
    assert order_success_rate(orders) == Decimal("0")


def test_order_success_rate_cancelled_not_filled():
    """cancelled 주문은 filled로 계산 안 됨."""
    orders = make_orders(["cancelled", "cancelled", "filled"])
    result = order_success_rate(orders)
    assert result == Decimal("1") / Decimal("3")


# ── win_rate ─────────────────────────────────────────────────────────────────────

def test_win_rate_empty_returns_zero():
    assert win_rate([]) == Decimal("0")


def test_win_rate_all_wins():
    trades = make_trades([100.0, 200.0, 50.0])
    assert win_rate(trades) == Decimal("1")


def test_win_rate_all_losses():
    trades = make_trades([-50.0, -100.0])
    assert win_rate(trades) == Decimal("0")


def test_win_rate_half():
    """2/4 수익 → 0.5."""
    trades = make_trades([100.0, -50.0, 200.0, -30.0])
    assert win_rate(trades) == Decimal("2") / Decimal("4")


def test_win_rate_pnl_zero_is_not_win():
    """PnL = 0은 수익이 아님 (> 0 기준)."""
    trades = make_trades([0.0, 100.0])
    result = win_rate(trades)
    assert result == Decimal("1") / Decimal("2")


def test_win_rate_single_win():
    trades = make_trades([50.0])
    assert win_rate(trades) == Decimal("1")


def test_win_rate_single_loss():
    trades = make_trades([-50.0])
    assert win_rate(trades) == Decimal("0")


# ── max_drawdown ─────────────────────────────────────────────────────────────────

def test_max_drawdown_empty_returns_zero():
    assert max_drawdown([]) == Decimal("0")


def test_max_drawdown_single_point_returns_zero():
    assert max_drawdown(make_balance_history([10000.0])) == Decimal("0")


def test_max_drawdown_monotonic_increase_is_zero():
    """잔고가 계속 오르면 낙폭 없음."""
    history = make_balance_history([10000.0, 10500.0, 11000.0, 12000.0])
    assert max_drawdown(history) == Decimal("0")


def test_max_drawdown_monotonic_decrease():
    """10000 → 8000: 낙폭 = (10000 - 8000) / 10000 = 0.2."""
    history = make_balance_history([10000.0, 9000.0, 8000.0])
    result = max_drawdown(history)
    assert result == Decimal("0.2")


def test_max_drawdown_recovery_does_not_hide_drawdown():
    """10000 → 7000 → 11000: 최대 낙폭 = 0.3 (회복 후에도 기록 유지)."""
    history = make_balance_history([10000.0, 7000.0, 11000.0])
    result = max_drawdown(history)
    assert result == Decimal("0.3")


def test_max_drawdown_multiple_valleys():
    """복수 낙폭 중 최대값 반환.

    10000 → 9000 (dd=0.1) → 10500 → 8400 (dd=0.2) → 10500
    최대 낙폭 = 0.2
    """
    history = make_balance_history([10000.0, 9000.0, 10500.0, 8400.0, 10500.0])
    result = max_drawdown(history)
    assert result == Decimal("0.2")


def test_max_drawdown_two_equal_points():
    """시작 = 끝 → 낙폭 없음."""
    history = make_balance_history([10000.0, 10000.0])
    assert max_drawdown(history) == Decimal("0")


# ── daily_pnl ────────────────────────────────────────────────────────────────────

def test_daily_pnl_no_trades_no_positions():
    result = daily_pnl([], [], today())
    assert result == Decimal("0")


def test_daily_pnl_today_realized_only():
    trades = [make_trade(realized_pnl=150.0, closed_today=True)]
    result = daily_pnl(trades, [], today())
    assert result == Decimal("150.0")


def test_daily_pnl_yesterday_trade_excluded():
    """어제 청산된 거래는 오늘 PnL에 포함되지 않음."""
    old = make_trade(realized_pnl=500.0, closed_today=False)
    result = daily_pnl([old], [], today())
    assert result == Decimal("0")


def test_daily_pnl_unrealized_only():
    positions = [make_position(unrealized_pnl=80.0)]
    result = daily_pnl([], positions, today())
    assert result == Decimal("80.0")


def test_daily_pnl_realized_plus_unrealized():
    trades = [make_trade(realized_pnl=100.0, closed_today=True)]
    positions = [make_position(unrealized_pnl=50.0)]
    result = daily_pnl(trades, positions, today())
    assert result == Decimal("150.0")


def test_daily_pnl_negative_unrealized():
    trades = [make_trade(realized_pnl=200.0, closed_today=True)]
    positions = [make_position(unrealized_pnl=-80.0)]
    result = daily_pnl(trades, positions, today())
    assert result == Decimal("120.0")


def test_daily_pnl_multiple_trades_today():
    trades = [
        make_trade(trade_id="t1", realized_pnl=100.0, closed_today=True),
        make_trade(trade_id="t2", realized_pnl=-40.0, closed_today=True),
        make_trade(trade_id="t3", realized_pnl=80.0, closed_today=False),  # 어제
    ]
    result = daily_pnl(trades, [], today())
    assert result == Decimal("60.0")


def test_daily_pnl_multiple_positions():
    positions = [
        make_position(symbol="BTCUSDT", unrealized_pnl=100.0),
        make_position(symbol="ETHUSDT", unrealized_pnl=-30.0),
    ]
    result = daily_pnl([], positions, today())
    assert result == Decimal("70.0")


# ── open_positions_count ──────────────────────────────────────────────────────────

def test_open_positions_count_empty():
    assert open_positions_count([]) == 0


def test_open_positions_count_one():
    assert open_positions_count([make_position()]) == 1


def test_open_positions_count_multiple():
    positions = [
        make_position(symbol="BTCUSDT"),
        make_position(symbol="ETHUSDT"),
        make_position(symbol="SOLUSDT"),
    ]
    assert open_positions_count(positions) == 3
