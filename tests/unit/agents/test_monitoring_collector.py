"""
MetricsCollector 테스트.

검증:
  - 빈 데이터 → MetricsSnapshot(all zeros)
  - snapshot 반환 타입 확인
  - total_orders / total_trades 카운트
  - order_success_rate 위임 확인
  - win_rate 위임 확인
  - max_drawdown 위임 확인
  - daily_pnl 위임 확인
  - open_positions_count 위임 확인
  - today 파라미터 사용
  - 각 호출마다 새 스냅샷 반환 (독립성)
  - computed_at이 datetime 타입
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from agents.monitoring.collector import MetricsCollector
from agents.monitoring.models import MetricsSnapshot

from tests.unit.agents._monitoring_fixtures import (
    make_balance_history,
    make_order,
    make_orders,
    make_position,
    make_trade,
    make_trades,
    today,
    yesterday_at,
)


def _collector() -> MetricsCollector:
    return MetricsCollector()


# ── 기본 반환 타입 ────────────────────────────────────────────────────────────────

def test_snapshot_returns_metrics_snapshot():
    snap = _collector().snapshot([], [], [], [], today())
    assert isinstance(snap, MetricsSnapshot)


def test_snapshot_empty_all_zeros():
    snap = _collector().snapshot([], [], [], [], today())
    assert snap.order_success_rate == Decimal("0")
    assert snap.win_rate == Decimal("0")
    assert snap.max_drawdown == Decimal("0")
    assert snap.daily_pnl == Decimal("0")
    assert snap.open_positions_count == 0
    assert snap.total_orders == 0
    assert snap.total_trades == 0


def test_snapshot_computed_at_is_datetime():
    snap = _collector().snapshot([], [], [], [], today())
    assert isinstance(snap.computed_at, datetime)


# ── 카운트 ────────────────────────────────────────────────────────────────────────

def test_snapshot_total_orders_count():
    orders = make_orders(["filled"] * 7)
    snap = _collector().snapshot(orders, [], [], [], today())
    assert snap.total_orders == 7


def test_snapshot_total_trades_count():
    trades = make_trades([100.0, -50.0, 200.0])
    snap = _collector().snapshot([], trades, [], [], today())
    assert snap.total_trades == 3


# ── 각 지표 위임 검증 ────────────────────────────────────────────────────────────

def test_snapshot_order_success_rate():
    """3/4 filled → 0.75."""
    orders = make_orders(["filled", "filled", "filled", "failed"])
    snap = _collector().snapshot(orders, [], [], [], today())
    assert snap.order_success_rate == Decimal("3") / Decimal("4")


def test_snapshot_win_rate():
    """2/3 수익 → 2/3."""
    trades = make_trades([100.0, 200.0, -50.0])
    snap = _collector().snapshot([], trades, [], [], today())
    assert snap.win_rate == Decimal("2") / Decimal("3")


def test_snapshot_max_drawdown():
    """10000 → 8000: drawdown = 0.2."""
    history = make_balance_history([10000.0, 8000.0])
    snap = _collector().snapshot([], [], [], history, today())
    assert snap.max_drawdown == Decimal("0.2")


def test_snapshot_daily_pnl_realized_only():
    trades = [make_trade(realized_pnl=300.0, closed_today=True)]
    snap = _collector().snapshot([], trades, [], [], today())
    assert snap.daily_pnl == Decimal("300.0")


def test_snapshot_daily_pnl_unrealized_only():
    positions = [make_position(unrealized_pnl=120.0)]
    snap = _collector().snapshot([], [], positions, [], today())
    assert snap.daily_pnl == Decimal("120.0")


def test_snapshot_open_positions_count():
    positions = [
        make_position(symbol="BTCUSDT"),
        make_position(symbol="ETHUSDT"),
    ]
    snap = _collector().snapshot([], [], positions, [], today())
    assert snap.open_positions_count == 2


# ── today 파라미터 ────────────────────────────────────────────────────────────────

def test_snapshot_respects_today_param():
    """어제 청산된 거래를 today=어제로 조회하면 포함된다."""
    from datetime import date as _date
    trade = make_trade(realized_pnl=500.0, closed_today=False)  # closed yesterday
    yesterday = _date(2026, 6, 6)
    snap = _collector().snapshot([], [trade], [], [], yesterday)
    assert snap.daily_pnl == Decimal("500.0")


def test_snapshot_excludes_old_trades_with_today_param():
    """today=오늘이면 어제 거래는 PnL에 미포함."""
    trade = make_trade(realized_pnl=500.0, closed_today=False)  # closed yesterday
    snap = _collector().snapshot([], [trade], [], [], today())
    assert snap.daily_pnl == Decimal("0")


# ── 독립성 ────────────────────────────────────────────────────────────────────────

def test_two_snapshots_are_independent():
    """같은 collector에서 두 번 호출 → 각기 독립적인 객체."""
    c = _collector()
    s1 = c.snapshot([], [], [], [], today())
    s2 = c.snapshot(make_orders(["filled"]), [], [], [], today())
    assert s1.total_orders == 0
    assert s2.total_orders == 1
    assert s1 is not s2


def test_collector_is_stateless():
    """MetricsCollector는 내부 상태를 보유하지 않는다."""
    c = _collector()
    c.snapshot(make_orders(["filled"] * 5), make_trades([100.0] * 3), [], [], today())
    snap2 = c.snapshot([], [], [], [], today())
    assert snap2.total_orders == 0
    assert snap2.total_trades == 0
