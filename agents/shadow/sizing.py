"""Risk-budget sizing used only by Shadow fast_exit_v2."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from agents.shadow.exchange_rules import SymbolRules, floor_to_step
from agents.shadow.pnl import (
    ShadowCostConfig,
    expected_fill_price,
    fill_fee,
    fill_slippage_cost,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class ShadowSizingInput:
    direction: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    equity_usdt: Decimal
    available_balance_usdt: Decimal
    risk_per_trade_pct: Decimal
    open_strategy_risk_usdt: Decimal
    max_portfolio_risk_pct: Decimal
    max_single_position_margin_ratio: Decimal
    margin_buffer_ratio: Decimal
    plan_max_leverage: int
    user_max_leverage: int
    system_max_leverage: int
    shadow_safe_leverage_cap: int
    funding_intervals: int
    symbol_rules: SymbolRules
    cost_config: ShadowCostConfig


@dataclass(frozen=True)
class ShadowSizingResult:
    approved: bool
    rejection_code: str | None = None
    rejection_reason: str | None = None
    quantity: Decimal = ZERO
    leverage: int = 1
    notional_usdt: Decimal = ZERO
    margin_usdt: Decimal = ZERO
    risk_budget_usdt: Decimal = ZERO
    actual_max_loss_usdt: Decimal = ZERO
    risk_budget_utilization: Decimal = ZERO
    worst_loss_per_coin: Decimal = ZERO
    leverage_reason: str = ""


def _reject(code: str, reason: str, budget: Decimal = ZERO) -> ShadowSizingResult:
    return ShadowSizingResult(
        approved=False,
        rejection_code=code,
        rejection_reason=reason,
        risk_budget_usdt=budget,
    )


def worst_loss_per_coin(inp: ShadowSizingInput) -> Decimal:
    entry = inp.entry_price
    stop = inp.stop_loss
    gross = abs(entry - stop)
    entry_fill = expected_fill_price(
        inp.direction, entry, inp.cost_config.slippage_bps, is_entry=True
    )
    stop_fill = expected_fill_price(
        inp.direction, stop, inp.cost_config.slippage_bps, is_entry=False
    )
    entry_fee = fill_fee(entry_fill, Decimal("1"), inp.cost_config.taker_fee_rate)
    exit_fee = fill_fee(stop_fill, Decimal("1"), inp.cost_config.taker_fee_rate)
    entry_slip = fill_slippage_cost(
        entry, Decimal("1"), inp.cost_config.slippage_bps
    )
    exit_slip = fill_slippage_cost(
        stop, Decimal("1"), inp.cost_config.slippage_bps
    )
    average_price = (entry + stop_fill) / Decimal("2")
    # Conservative sizing never counts a possible funding credit as profit.
    funding = (
        average_price
        * abs(inp.cost_config.funding_rate_per_interval)
        * Decimal(max(1, inp.funding_intervals))
    )
    return gross + entry_fee + exit_fee + entry_slip + exit_slip + funding


def size_from_risk_budget(inp: ShadowSizingInput) -> ShadowSizingResult:
    if inp.direction not in {"LONG", "SHORT"}:
        return _reject("INVALID_DIRECTION", f"unsupported direction {inp.direction}")
    if min(
        inp.entry_price,
        inp.stop_loss,
        inp.take_profit,
        inp.equity_usdt,
        inp.available_balance_usdt,
    ) <= ZERO:
        return _reject("INVALID_SIZING_INPUT", "prices, equity and balance must be positive")
    if not ZERO < inp.risk_per_trade_pct <= Decimal("1"):
        return _reject("INVALID_RISK_PCT", "risk_per_trade_pct must be in (0, 1]")
    if inp.margin_buffer_ratio < Decimal("1"):
        return _reject("INVALID_MARGIN_BUFFER", "margin_buffer_ratio must be >= 1")

    budget = inp.equity_usdt * inp.risk_per_trade_pct
    loss_per_coin = worst_loss_per_coin(inp)
    if loss_per_coin <= ZERO:
        return _reject("INVALID_WORST_LOSS", "worst loss per coin must be positive", budget)

    raw_quantity = budget / loss_per_coin
    rules = inp.symbol_rules
    quantity = floor_to_step(raw_quantity, rules.quantity_step)
    if quantity < rules.min_quantity:
        return _reject("MIN_QUANTITY", "risk-sized quantity is below minimum", budget)

    max_single_margin = min(
        inp.equity_usdt * inp.max_single_position_margin_ratio,
        inp.available_balance_usdt / inp.margin_buffer_ratio,
    )
    max_leverage = min(
        inp.plan_max_leverage,
        inp.user_max_leverage,
        inp.system_max_leverage,
        inp.shadow_safe_leverage_cap,
    )
    if max_single_margin <= ZERO or max_leverage < 1:
        return _reject("NO_MARGIN_CAPACITY", "no usable margin or leverage", budget)

    notional = quantity * inp.entry_price
    required_leverage = int(
        (notional / max_single_margin).to_integral_value(rounding=ROUND_CEILING)
    )
    leverage_reason = "minimum leverage satisfying isolated margin cap"
    if required_leverage > max_leverage:
        max_notional = max_single_margin * Decimal(max_leverage)
        quantity = floor_to_step(
            min(quantity, max_notional / inp.entry_price), rules.quantity_step
        )
        leverage_reason = "quantity reduced to satisfy maximum allowed leverage"
        if quantity < rules.min_quantity:
            return _reject("LEVERAGE_CAP", "quantity below minimum after leverage cap", budget)
        notional = quantity * inp.entry_price
        required_leverage = int(
            (notional / max_single_margin).to_integral_value(rounding=ROUND_CEILING)
        )

    leverage = max(1, required_leverage)
    margin = notional / Decimal(leverage)
    actual_loss = quantity * loss_per_coin
    utilization = actual_loss / budget if budget > ZERO else ZERO

    if notional < rules.min_notional:
        return _reject("MIN_NOTIONAL", "risk-sized notional is below minimum", budget)
    if margin * inp.margin_buffer_ratio > inp.available_balance_usdt:
        return _reject("INSUFFICIENT_BALANCE", "margin buffer exceeds available balance", budget)
    if actual_loss > budget:
        return _reject("RISK_BUDGET_EXCEEDED", "actual max loss exceeds risk budget", budget)
    portfolio_limit = inp.equity_usdt * inp.max_portfolio_risk_pct
    if inp.open_strategy_risk_usdt + actual_loss > portfolio_limit:
        return _reject(
            "PORTFOLIO_RISK_EXCEEDED",
            "strategy ledger portfolio risk would exceed limit",
            budget,
        )

    return ShadowSizingResult(
        approved=True,
        quantity=quantity,
        leverage=leverage,
        notional_usdt=notional,
        margin_usdt=margin,
        risk_budget_usdt=budget,
        actual_max_loss_usdt=actual_loss,
        risk_budget_utilization=utilization,
        worst_loss_per_coin=loss_per_coin,
        leverage_reason=leverage_reason,
    )


def evaluate_fixed_quantity_risk(
    inp: ShadowSizingInput,
    *,
    quantity: Decimal,
    leverage: int,
    margin_usdt: Decimal,
) -> ShadowSizingResult:
    """Compute mandatory cost-inclusive risk metadata without resizing."""
    rules = inp.symbol_rules
    budget = inp.equity_usdt * inp.risk_per_trade_pct
    if quantity <= ZERO or quantity < rules.min_quantity:
        return _reject("MIN_QUANTITY", "fixed quantity is below minimum", budget)
    if quantity != floor_to_step(quantity, rules.quantity_step):
        return _reject("LOT_STEP", "fixed quantity does not match lot step", budget)
    if leverage < 1:
        return _reject("INVALID_LEVERAGE", "fixed leverage must be positive", budget)
    loss_per_coin = worst_loss_per_coin(inp)
    actual_loss = quantity * loss_per_coin
    notional = quantity * inp.entry_price
    utilization = actual_loss / budget if budget > ZERO else ZERO
    if actual_loss > budget:
        return _reject(
            "RISK_BUDGET_EXCEEDED",
            "fixed quantity actual max loss exceeds risk budget",
            budget,
        )
    if (
        inp.open_strategy_risk_usdt + actual_loss
        > inp.equity_usdt * inp.max_portfolio_risk_pct
    ):
        return _reject(
            "PORTFOLIO_RISK_EXCEEDED",
            "all-strategy portfolio risk would exceed limit",
            budget,
        )
    return ShadowSizingResult(
        approved=True,
        quantity=quantity,
        leverage=leverage,
        notional_usdt=notional,
        margin_usdt=margin_usdt,
        risk_budget_usdt=budget,
        actual_max_loss_usdt=actual_loss,
        risk_budget_utilization=utilization,
        worst_loss_per_coin=loss_per_coin,
        leverage_reason="existing baseline sizing; cost-inclusive risk recomputed",
    )
