"""
PaperPosition / PaperTradeRecord / PaperUserSettings 모델 단위 테스트.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.paper_trading.models import (
    PaperPosition,
    PaperTradeRecord,
    PaperUserSettings,
)


# ── PaperUserSettings ──────────────────────────────────────────────────────────

class TestPaperUserSettings:
    def test_defaults(self):
        s = PaperUserSettings(user_id="u1")
        assert s.plan == "pro"
        assert s.risk_profile == "moderate"
        assert s.risk_per_trade == 0.02
        assert s.max_leverage == 10
        assert s.daily_loss_limit_pct == 0.03
        assert s.is_trading_active is True

    def test_custom(self):
        s = PaperUserSettings(
            user_id="u1",
            plan="elite",
            risk_profile="aggressive",
            max_leverage=20,
        )
        assert s.plan == "elite"
        assert s.max_leverage == 20


# ── PaperPosition ──────────────────────────────────────────────────────────────

def _make_position(direction="LONG", entry=Decimal("67450"), current=None) -> PaperPosition:
    current = current or entry
    return PaperPosition(
        id="pos-1",
        user_id="u1",
        coin="BTC",
        symbol="BTCUSDT",
        direction=direction,
        entry_price=entry,
        quantity=Decimal("0.007"),
        original_quantity=Decimal("0.007"),
        leverage=5,
        take_profit=Decimal("69200") if direction == "LONG" else Decimal("65700"),
        stop_loss=Decimal("66800") if direction == "LONG" else Decimal("68100"),
        liquidation_price=Decimal("54500") if direction == "LONG" else Decimal("80500"),
        margin_used=Decimal("100"),
        original_margin=Decimal("100"),
        max_loss_usdt=Decimal("45.5"),
        max_profit_usdt=Decimal("123"),
        original_risk_usdt=Decimal("45.5"),
        current_price=current,
    )


class TestPaperPositionProperties:
    def test_unrealized_long_profit(self):
        pos = _make_position("LONG", Decimal("67450"), current=Decimal("68000"))
        expected = (Decimal("68000") - Decimal("67450")) * Decimal("0.007")
        assert pos.unrealized_pnl == expected

    def test_unrealized_long_loss(self):
        pos = _make_position("LONG", Decimal("67450"), current=Decimal("67000"))
        expected = (Decimal("67000") - Decimal("67450")) * Decimal("0.007")
        assert pos.unrealized_pnl == expected
        assert pos.unrealized_pnl < 0

    def test_unrealized_short_profit(self):
        pos = _make_position("SHORT", Decimal("67450"), current=Decimal("66000"))
        expected = (Decimal("67450") - Decimal("66000")) * Decimal("0.007")
        assert pos.unrealized_pnl == expected
        assert pos.unrealized_pnl > 0

    def test_unrealized_short_loss(self):
        pos = _make_position("SHORT", Decimal("67450"), current=Decimal("68000"))
        expected = (Decimal("67450") - Decimal("68000")) * Decimal("0.007")
        assert pos.unrealized_pnl == expected
        assert pos.unrealized_pnl < 0

    def test_unrealized_zero_when_closed(self):
        pos = _make_position("LONG", Decimal("67450"), current=Decimal("70000"))
        pos.status = "closed"
        assert pos.unrealized_pnl == Decimal("0")

    def test_unrealized_zero_when_no_current_price(self):
        pos = _make_position("LONG")
        pos.current_price = Decimal("0")
        assert pos.unrealized_pnl == Decimal("0")

    def test_is_open_true(self):
        pos = _make_position()
        assert pos.is_open is True

    def test_is_open_false_when_closed(self):
        pos = _make_position()
        pos.status = "closed"
        assert pos.is_open is False

    def test_is_open_true_when_partially_closed(self):
        pos = _make_position()
        pos.status = "partially_closed"
        assert pos.is_open is True

    def test_pnl_pct(self):
        pos = _make_position("LONG", Decimal("67450"), current=Decimal("67450"))
        pos.realized_pnl = Decimal("10")
        # pnl_pct = (realized + unrealized) / original_margin * 100
        # = 10 / 100 * 100 = 10%
        assert pos.pnl_pct == Decimal("10.00")

    def test_total_pnl(self):
        pos = _make_position("LONG", Decimal("67450"), current=Decimal("68000"))
        pos.realized_pnl = Decimal("5")
        unrealized = (Decimal("68000") - Decimal("67450")) * Decimal("0.007")
        assert pos.total_pnl == Decimal("5") + unrealized


# ── PaperTradeRecord ───────────────────────────────────────────────────────────

class TestPaperTradeRecord:
    def test_record_creation(self):
        now = datetime.now(timezone.utc)
        record = PaperTradeRecord(
            id="tr-1",
            position_id="pos-1",
            user_id="u1",
            coin="BTC",
            direction="LONG",
            entry_price=Decimal("67450"),
            close_price=Decimal("69200"),
            quantity=Decimal("0.007"),
            leverage=5,
            gross_pnl=Decimal("12.25"),
            fee=Decimal("0.28"),
            net_pnl=Decimal("11.97"),
            pnl_pct=Decimal("11.97"),
            duration_seconds=3600,
            close_reason="tp_hit",
            opened_at=now,
            closed_at=now,
        )
        assert record.net_pnl > 0
        assert record.close_reason == "tp_hit"
        assert record.is_partial is False

    def test_partial_record(self):
        now = datetime.now(timezone.utc)
        record = PaperTradeRecord(
            id="tr-2",
            position_id="pos-1",
            user_id="u1",
            coin="ETH",
            direction="SHORT",
            entry_price=Decimal("3500"),
            close_price=Decimal("3400"),
            quantity=Decimal("0.1"),
            leverage=3,
            gross_pnl=Decimal("10"),
            fee=Decimal("0.24"),
            net_pnl=Decimal("9.76"),
            pnl_pct=Decimal("9.76"),
            duration_seconds=1800,
            close_reason="partial",
            is_partial=True,
            opened_at=now,
            closed_at=now,
        )
        assert record.is_partial is True
        assert record.close_reason == "partial"
