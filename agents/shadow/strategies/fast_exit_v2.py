"""Shadow-only fast exit transformation. The source candidate is never mutated."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING
from typing import Any

from agents.shadow.exchange_rules import SymbolRules, round_exit_price
from agents.shadow.pnl import (
    ShadowCostConfig,
    expected_fill_price,
    fill_fee,
    fill_slippage_cost,
)


@dataclass(frozen=True)
class FastExitConfig:
    tp_pct: Decimal
    sl_pct: Decimal
    min_sl_pct: Decimal
    max_hold_seconds: int
    min_rr: Decimal
    min_tp_cost_multiple: Decimal


@dataclass(frozen=True)
class FastExitResult:
    approved: bool
    candidate: Any = None
    rejection_code: str | None = None
    rejection_reason: str | None = None
    expected_tp_net_profit_per_coin: Decimal = Decimal("0")
    expected_round_trip_cost_per_coin: Decimal = Decimal("0")
    funding_intervals: int = 1


def _reject(code: str, reason: str) -> FastExitResult:
    return FastExitResult(False, rejection_code=code, rejection_reason=reason)


def _funding_intervals(max_hold_seconds: int, interval_hours: int) -> int:
    interval_seconds = Decimal(interval_hours * 3600)
    return max(
        1,
        int(
            (Decimal(max_hold_seconds) / interval_seconds).to_integral_value(
                rounding=ROUND_CEILING
            )
        ),
    )


def build_fast_exit(
    candidate: Any,
    *,
    config: FastExitConfig,
    cost_config: ShadowCostConfig,
    rules: SymbolRules,
) -> FastExitResult:
    direction = str(getattr(getattr(candidate, "action", None), "value", getattr(candidate, "action", "")))
    if direction not in {"LONG", "SHORT"}:
        return _reject("INVALID_DIRECTION", "fast_exit_v2 requires LONG or SHORT")
    entry = candidate.entry_price
    if not all(isinstance(v, Decimal) for v in (entry, config.tp_pct, config.sl_pct, config.min_sl_pct)):
        return _reject("DECIMAL_REQUIRED", "price and percentage inputs must be Decimal")
    if entry <= 0 or min(config.tp_pct, config.sl_pct, config.min_sl_pct) <= 0:
        return _reject("INVALID_FAST_EXIT_CONFIG", "entry and exit percentages must be positive")

    tp_distance = entry * config.tp_pct
    desired_sl_distance = entry * max(config.sl_pct, config.min_sl_pct)
    if direction == "LONG":
        raw_tp = entry + tp_distance
        raw_sl = entry - desired_sl_distance
    else:
        raw_tp = entry - tp_distance
        raw_sl = entry + desired_sl_distance
    tp = round_exit_price(raw_tp, rules.price_tick, direction, "TP")
    sl = round_exit_price(raw_sl, rules.price_tick, direction, "SL")

    reward = tp - entry if direction == "LONG" else entry - tp
    risk = entry - sl if direction == "LONG" else sl - entry
    if reward <= 0:
        return _reject("NON_POSITIVE_TP_PROFIT", "expected TP gross profit is not positive")
    if risk <= 0:
        return _reject("INVALID_SL_DIRECTION", "stop loss is on the wrong side")
    rr = reward / risk
    if rr < config.min_rr:
        return _reject("MIN_RR_NOT_MET", f"fast exit R:R {rr} is below {config.min_rr}")

    intervals = _funding_intervals(
        config.max_hold_seconds, cost_config.funding_interval_hours
    )
    entry_fee = fill_fee(
        expected_fill_price(
            direction, entry, cost_config.slippage_bps, is_entry=True
        ),
        Decimal("1"),
        cost_config.taker_fee_rate,
    )
    exit_fee = fill_fee(
        expected_fill_price(
            direction, tp, cost_config.slippage_bps, is_entry=False
        ),
        Decimal("1"),
        cost_config.taker_fee_rate,
    )
    entry_slip = fill_slippage_cost(entry, Decimal("1"), cost_config.slippage_bps)
    exit_slip = fill_slippage_cost(tp, Decimal("1"), cost_config.slippage_bps)
    average_price = (entry + tp) / Decimal("2")
    funding = (
        average_price
        * abs(cost_config.funding_rate_per_interval)
        * Decimal(intervals)
    )
    costs = entry_fee + exit_fee + entry_slip + exit_slip + funding
    net = reward - costs
    if net <= 0:
        return _reject("NON_POSITIVE_TP_NET", "expected TP net profit is not positive")
    if net < costs * config.min_tp_cost_multiple:
        return _reject(
            "TP_COST_MULTIPLE_NOT_MET",
            "expected TP net profit is below configured cost multiple",
        )

    adjusted = replace(
        candidate,
        take_profit=tp,
        stop_loss=sl,
        expected_holding_minutes=max(1, config.max_hold_seconds // 60),
        actual_rr=float(rr),
        reasons=list(candidate.reasons)
        + ["[shadow fast_exit_v2] independent TP/SL and max-hold policy"],
    )
    return FastExitResult(
        approved=True,
        candidate=adjusted,
        expected_tp_net_profit_per_coin=net,
        expected_round_trip_cost_per_coin=costs,
        funding_intervals=intervals,
    )
