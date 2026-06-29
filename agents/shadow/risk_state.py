"""Shadow-only loss state reconstructed from persisted closed trades."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable


class UnresolvedOpenRiskError(RuntimeError):
    """An OPEN Shadow row lacks cost-inclusive risk metadata."""


@dataclass(frozen=True)
class ClosedShadowPnl:
    closed_at: datetime
    net_pnl_usdt: Decimal | None
    gross_pnl_usdt: Decimal | None


@dataclass(frozen=True)
class ShadowLossState:
    daily_loss_usdt: Decimal = Decimal("0")
    consecutive_losses: int = 0
    used_gross_fallback: bool = False


def rebuild_loss_state(
    rows: Iterable[ClosedShadowPnl],
    *,
    now: datetime | None = None,
) -> ShadowLossState:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ordered = sorted(rows, key=lambda row: row.closed_at)
    daily_loss = Decimal("0")
    used_fallback = False
    values: list[Decimal] = []
    for row in ordered:
        pnl = row.net_pnl_usdt
        if pnl is None:
            pnl = row.gross_pnl_usdt
            used_fallback = True
        if pnl is None:
            continue
        values.append(pnl)
        if row.closed_at.astimezone(timezone.utc).date() == current.date() and pnl < 0:
            daily_loss += abs(pnl)

    consecutive = 0
    for pnl in reversed(values):
        if pnl < 0:
            consecutive += 1
        else:
            break
    return ShadowLossState(daily_loss, consecutive, used_fallback)
