"""Deterministic PnL and cost calculations for Binance USD-M shadow trades."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

Direction = Literal["LONG", "SHORT"]
ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
TEN_THOUSAND = Decimal("10000")
MONEY_Q = Decimal("0.00000001")


@dataclass(frozen=True)
class ShadowCostConfig:
    """Conservative taker defaults for virtual market fills."""

    taker_fee_rate: Decimal = Decimal("0.0004")  # 0.04% per fill
    slippage_bps: Decimal = Decimal("5")         # 0.05% per fill
    funding_rate_per_interval: Decimal = Decimal("0.0001")  # signed, 0.01%
    funding_interval_hours: int = 8

    def __post_init__(self) -> None:
        if not ZERO <= self.taker_fee_rate <= Decimal("0.1"):
            raise ValueError("taker_fee_rate must be between 0 and 0.1")
        if not ZERO <= self.slippage_bps <= Decimal("1000"):
            raise ValueError("slippage_bps must be between 0 and 1000")
        if self.funding_interval_hours <= 0 or 24 % self.funding_interval_hours:
            raise ValueError("funding_interval_hours must be a positive divisor of 24")


@dataclass(frozen=True)
class ShadowPnl:
    gross_pnl_usdt: Decimal
    entry_fee_usdt: Decimal
    exit_fee_usdt: Decimal
    funding_fee_usdt: Decimal
    entry_slippage_usdt: Decimal
    exit_slippage_usdt: Decimal
    slippage_cost_usdt: Decimal
    net_pnl_usdt: Decimal
    net_return_on_margin_pct: Decimal | None


def gross_pnl(
    direction: Direction,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if direction == "LONG":
        return (exit_price - entry_price) * quantity
    if direction == "SHORT":
        return (entry_price - exit_price) * quantity
    raise ValueError(f"unsupported direction: {direction}")


def fill_fee(price: Decimal, quantity: Decimal, fee_rate: Decimal) -> Decimal:
    return (price * quantity * fee_rate).quantize(MONEY_Q)


def fill_slippage_cost(
    price: Decimal, quantity: Decimal, slippage_bps: Decimal
) -> Decimal:
    return (price * quantity * slippage_bps / TEN_THOUSAND).quantize(MONEY_Q)


def expected_fill_price(
    direction: Direction,
    price: Decimal,
    slippage_bps: Decimal,
    *,
    is_entry: bool,
) -> Decimal:
    rate = slippage_bps / TEN_THOUSAND
    is_buy = (direction == "LONG" and is_entry) or (
        direction == "SHORT" and not is_entry
    )
    return price * (Decimal("1") + rate if is_buy else Decimal("1") - rate)


def funding_event_count(
    opened_at: datetime, closed_at: datetime, interval_hours: int
) -> int:
    """Count UTC funding boundaries in (opened_at, closed_at]."""
    start = opened_at.astimezone(timezone.utc)
    end = closed_at.astimezone(timezone.utc)
    if end <= start:
        return 0
    cursor = start.replace(minute=0, second=0, microsecond=0)
    while cursor <= start or cursor.hour % interval_hours:
        cursor += timedelta(hours=1)
    count = 0
    while cursor <= end:
        count += 1
        cursor += timedelta(hours=interval_hours)
    return count


def calculate_shadow_pnl(
    *,
    direction: Direction,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    margin_usdt: Decimal | None,
    opened_at: datetime,
    closed_at: datetime,
    config: ShadowCostConfig,
) -> ShadowPnl:
    gross = gross_pnl(direction, entry_price, exit_price, quantity)
    entry_fill = expected_fill_price(
        direction, entry_price, config.slippage_bps, is_entry=True
    )
    exit_fill = expected_fill_price(
        direction, exit_price, config.slippage_bps, is_entry=False
    )
    entry_fee = fill_fee(entry_fill, quantity, config.taker_fee_rate)
    exit_fee = fill_fee(exit_fill, quantity, config.taker_fee_rate)
    entry_slippage = fill_slippage_cost(
        entry_price, quantity, config.slippage_bps
    )
    exit_slippage = fill_slippage_cost(exit_price, quantity, config.slippage_bps)
    slippage = entry_slippage + exit_slippage
    funding_events = funding_event_count(
        opened_at, closed_at, config.funding_interval_hours
    )
    # Funding uses an average-notional estimate because interval mark prices are
    # not currently retained. Positive rates cost LONGs and credit SHORTs.
    avg_notional = ((entry_price + exit_price) / Decimal("2")) * quantity
    funding = (
        avg_notional
        * config.funding_rate_per_interval
        * Decimal(funding_events)
        * (Decimal("1") if direction == "LONG" else Decimal("-1"))
    ).quantize(MONEY_Q)
    net = (gross - entry_fee - exit_fee - funding - slippage).quantize(MONEY_Q)
    return_pct = None
    if margin_usdt is not None and margin_usdt > ZERO:
        return_pct = (net / margin_usdt * ONE_HUNDRED).quantize(Decimal("0.0001"))
    return ShadowPnl(
        gross_pnl_usdt=gross.quantize(MONEY_Q),
        entry_fee_usdt=entry_fee,
        exit_fee_usdt=exit_fee,
        funding_fee_usdt=funding,
        entry_slippage_usdt=entry_slippage,
        exit_slippage_usdt=exit_slippage,
        slippage_cost_usdt=slippage,
        net_pnl_usdt=net,
        net_return_on_margin_pct=return_pct,
    )
