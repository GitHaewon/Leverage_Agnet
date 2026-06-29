from datetime import datetime, timezone
from decimal import Decimal

from agents.shadow.risk_state import ClosedShadowPnl, rebuild_loss_state

UTC = timezone.utc


def _row(day: int, hour: int, net: str | None, gross: str | None = None):
    return ClosedShadowPnl(
        datetime(2026, 6, day, hour, tzinfo=UTC),
        Decimal(net) if net is not None else None,
        Decimal(gross) if gross is not None else None,
    )


def test_daily_loss_uses_current_utc_date_only():
    state = rebuild_loss_state(
        [_row(28, 23, "-10"), _row(29, 1, "-20"), _row(29, 2, "5")],
        now=datetime(2026, 6, 29, 3, tzinfo=UTC),
    )
    assert state.daily_loss_usdt == Decimal("20")


def test_consecutive_losses_reset_after_profit():
    state = rebuild_loss_state(
        [_row(29, 1, "-10"), _row(29, 2, "5"), _row(29, 3, "-2")],
        now=datetime(2026, 6, 29, 4, tzinfo=UTC),
    )
    assert state.consecutive_losses == 1


def test_legacy_gross_fallback_is_explicit():
    state = rebuild_loss_state(
        [_row(29, 1, None, "-7")],
        now=datetime(2026, 6, 29, 4, tzinfo=UTC),
    )
    assert state.daily_loss_usdt == Decimal("7")
    assert state.used_gross_fallback
