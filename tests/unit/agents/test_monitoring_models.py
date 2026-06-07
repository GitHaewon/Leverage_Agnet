"""
Monitoring 데이터 모델 테스트.

검증:
  - OrderRecord 필드 보존
  - TradeRecord 필드 보존
  - PositionSnapshot 필드 보존
  - MetricsSnapshot 기본값 및 필드
  - MetricsSnapshot.computed_at 자동 설정
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agents.monitoring.models import (
    MetricsSnapshot,
    OrderRecord,
    PositionSnapshot,
    TradeRecord,
)

from tests.unit.agents._monitoring_fixtures import now_at


# ── OrderRecord ───────────────────────────────────────────────────────────────────

def test_order_record_fields_preserved():
    ts = now_at(9)
    rec = OrderRecord(order_id="ord-001", symbol="BTCUSDT", status="filled", submitted_at=ts)
    assert rec.order_id == "ord-001"
    assert rec.symbol == "BTCUSDT"
    assert rec.status == "filled"
    assert rec.submitted_at == ts


def test_order_record_failed_status():
    rec = OrderRecord(
        order_id="ord-002", symbol="ETHUSDT", status="failed",
        submitted_at=now_at(10),
    )
    assert rec.status == "failed"


def test_order_record_cancelled_status():
    rec = OrderRecord(
        order_id="ord-003", symbol="BTCUSDT", status="cancelled",
        submitted_at=now_at(11),
    )
    assert rec.status == "cancelled"


# ── TradeRecord ───────────────────────────────────────────────────────────────────

def test_trade_record_fields_preserved():
    ts = now_at(14)
    trade = TradeRecord(
        trade_id="trd-001",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("67000"),
        exit_price=Decimal("69000"),
        quantity=Decimal("0.001"),
        realized_pnl=Decimal("150.0"),
        closed_at=ts,
    )
    assert trade.trade_id == "trd-001"
    assert trade.direction == "LONG"
    assert trade.realized_pnl == Decimal("150.0")
    assert trade.closed_at == ts


def test_trade_record_negative_pnl():
    trade = TradeRecord(
        trade_id="trd-002",
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=Decimal("3500"),
        exit_price=Decimal("3600"),
        quantity=Decimal("0.1"),
        realized_pnl=Decimal("-10.0"),
        closed_at=now_at(15),
    )
    assert trade.realized_pnl < 0


def test_trade_record_short_direction():
    trade = TradeRecord(
        trade_id="trd-003",
        symbol="BTCUSDT",
        direction="SHORT",
        entry_price=Decimal("68000"),
        exit_price=Decimal("66000"),
        quantity=Decimal("0.001"),
        realized_pnl=Decimal("200.0"),
        closed_at=now_at(16),
    )
    assert trade.direction == "SHORT"


# ── PositionSnapshot ──────────────────────────────────────────────────────────────

def test_position_snapshot_fields_preserved():
    pos = PositionSnapshot(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("67000"),
        current_price=Decimal("67500"),
        quantity=Decimal("0.001"),
        leverage=5,
        unrealized_pnl=Decimal("50.0"),
    )
    assert pos.symbol == "BTCUSDT"
    assert pos.leverage == 5
    assert pos.unrealized_pnl == Decimal("50.0")


def test_position_snapshot_negative_unrealized():
    pos = PositionSnapshot(
        symbol="ETHUSDT",
        direction="LONG",
        entry_price=Decimal("3500"),
        current_price=Decimal("3400"),
        quantity=Decimal("0.1"),
        leverage=3,
        unrealized_pnl=Decimal("-10.0"),
    )
    assert pos.unrealized_pnl < 0


# ── MetricsSnapshot ───────────────────────────────────────────────────────────────

def test_metrics_snapshot_fields_set():
    ts = now_at(12)
    snap = MetricsSnapshot(
        order_success_rate=Decimal("0.9"),
        win_rate=Decimal("0.6"),
        max_drawdown=Decimal("0.12"),
        daily_pnl=Decimal("250.0"),
        open_positions_count=2,
        total_orders=10,
        total_trades=5,
        computed_at=ts,
    )
    assert snap.order_success_rate == Decimal("0.9")
    assert snap.win_rate == Decimal("0.6")
    assert snap.max_drawdown == Decimal("0.12")
    assert snap.daily_pnl == Decimal("250.0")
    assert snap.open_positions_count == 2
    assert snap.total_orders == 10
    assert snap.total_trades == 5
    assert snap.computed_at == ts


def test_metrics_snapshot_computed_at_auto():
    """computed_at 미지정 시 자동으로 현재 시각 설정."""
    snap = MetricsSnapshot(
        order_success_rate=Decimal("0"),
        win_rate=Decimal("0"),
        max_drawdown=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_positions_count=0,
        total_orders=0,
        total_trades=0,
    )
    assert snap.computed_at is not None
    assert isinstance(snap.computed_at, datetime)


def test_metrics_snapshot_negative_daily_pnl():
    """daily_pnl은 음수 가능."""
    snap = MetricsSnapshot(
        order_success_rate=Decimal("0.5"),
        win_rate=Decimal("0.3"),
        max_drawdown=Decimal("0.25"),
        daily_pnl=Decimal("-80.0"),
        open_positions_count=1,
        total_orders=4,
        total_trades=3,
    )
    assert snap.daily_pnl < 0
