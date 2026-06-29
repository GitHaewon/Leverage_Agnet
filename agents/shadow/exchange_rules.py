"""Explicit Shadow-only exchange rules.

The repository does not currently persist Binance exchangeInfo.  These rules
therefore mirror the existing centrally-supported BTC/ETH symbols; unknown
symbols fail closed instead of inheriting BTC defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    quantity_step: Decimal
    min_quantity: Decimal
    price_tick: Decimal
    min_notional: Decimal


# [ASSUMPTION] Repository-supported rules until exchangeInfo is persisted.
SHADOW_SYMBOL_RULES: dict[str, SymbolRules] = {
    "BTCUSDT": SymbolRules(
        "BTCUSDT", Decimal("0.001"), Decimal("0.001"), Decimal("0.1"), Decimal("5")
    ),
    "ETHUSDT": SymbolRules(
        "ETHUSDT", Decimal("0.01"), Decimal("0.01"), Decimal("0.01"), Decimal("5")
    ),
}


def get_symbol_rules(symbol: str) -> SymbolRules | None:
    return SHADOW_SYMBOL_RULES.get(symbol)


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def round_exit_price(
    price: Decimal, tick: Decimal, direction: str, purpose: str
) -> Decimal:
    """Round toward a conservative executable trigger."""
    if (direction == "LONG" and purpose == "TP") or (
        direction == "SHORT" and purpose == "SL"
    ):
        return floor_to_step(price, tick)
    return ceil_to_step(price, tick)
