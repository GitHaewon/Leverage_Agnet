"""Configuration and pure planning for the opt-in Shadow experiment."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agents.risk.constants import PLAN_MAX_LEVERAGE
from agents.shadow.exchange_rules import get_symbol_rules
from agents.shadow.pnl import ShadowCostConfig
from agents.shadow.sizing import (
    ShadowSizingInput,
    ShadowSizingResult,
    evaluate_fixed_quantity_risk,
    size_from_risk_budget,
)
from agents.shadow.strategies.fast_exit_v2 import (
    FastExitConfig,
    FastExitResult,
    build_fast_exit,
)


@dataclass(frozen=True)
class ShadowExperimentConfig:
    fast_exit_enabled: bool = False
    risk_sizing_enabled: bool = False
    experiment_label: str = "fast_exit_v2_ab"
    fast_exit: FastExitConfig | None = None
    risk_per_trade_pct: Decimal = Decimal("0.01")
    safe_max_leverage: int = 5
    max_portfolio_risk_pct: Decimal = Decimal("0.10")
    max_single_position_margin_ratio: Decimal = Decimal("0.20")
    margin_buffer_ratio: Decimal = Decimal("1.10")
    system_max_leverage: int = 20

    @property
    def active(self) -> bool:
        return self.fast_exit_enabled or self.risk_sizing_enabled

    def validate(self) -> None:
        if self.fast_exit_enabled and self.fast_exit is None:
            raise ValueError("fast_exit settings are required when enabled")
        if not Decimal("0") < self.risk_per_trade_pct <= Decimal("1"):
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        if self.safe_max_leverage < 1:
            raise ValueError("safe_max_leverage must be >= 1")


@dataclass(frozen=True)
class FastExitPlan:
    exit_result: FastExitResult
    sizing_result: ShadowSizingResult | None = None

    @property
    def approved(self) -> bool:
        return self.exit_result.approved and bool(
            self.sizing_result is None or self.sizing_result.approved
        )


def plan_fast_exit(
    candidate: Any,
    *,
    user_ctx: Any,
    account: Any,
    open_strategy_risk_usdt: Decimal,
    baseline_quantity: Decimal,
    baseline_leverage: int,
    baseline_margin_usdt: Decimal,
    config: ShadowExperimentConfig,
    cost_config: ShadowCostConfig,
) -> FastExitPlan:
    config.validate()
    rules = get_symbol_rules(candidate.symbol)
    if rules is None:
        return FastExitPlan(
            FastExitResult(
                approved=False,
                rejection_code="UNSUPPORTED_SYMBOL_RULES",
                rejection_reason=f"no Shadow exchange rules for {candidate.symbol}",
            )
        )
    if not config.fast_exit_enabled:
        return FastExitPlan(
            FastExitResult(
                approved=False,
                rejection_code="FAST_EXIT_DISABLED",
                rejection_reason="fast_exit_v2 feature flag is disabled",
            )
        )
    exit_result = build_fast_exit(
        candidate,
        config=config.fast_exit,  # type: ignore[arg-type]
        cost_config=cost_config,
        rules=rules,
    )
    if not exit_result.approved:
        return FastExitPlan(exit_result)

    equity = Decimal(str(getattr(account, "total_balance", 0) or 0))
    available = Decimal(str(getattr(account, "available_balance", 0) or 0))
    plan = str(getattr(user_ctx, "plan", "free") or "free")
    sizing_input = ShadowSizingInput(
            direction=exit_result.candidate.action.value,
            entry_price=exit_result.candidate.entry_price,
            stop_loss=exit_result.candidate.stop_loss,
            take_profit=exit_result.candidate.take_profit,
            equity_usdt=equity,
            available_balance_usdt=available,
            risk_per_trade_pct=config.risk_per_trade_pct,
            open_strategy_risk_usdt=open_strategy_risk_usdt,
            max_portfolio_risk_pct=config.max_portfolio_risk_pct,
            max_single_position_margin_ratio=config.max_single_position_margin_ratio,
            margin_buffer_ratio=config.margin_buffer_ratio,
            plan_max_leverage=PLAN_MAX_LEVERAGE.get(plan, PLAN_MAX_LEVERAGE["free"]),
            user_max_leverage=int(getattr(user_ctx, "max_leverage", 1) or 1),
            system_max_leverage=config.system_max_leverage,
            shadow_safe_leverage_cap=config.safe_max_leverage,
            funding_intervals=exit_result.funding_intervals,
            symbol_rules=rules,
            cost_config=cost_config,
        )
    sizing = (
        size_from_risk_budget(sizing_input)
        if config.risk_sizing_enabled
        else evaluate_fixed_quantity_risk(
            sizing_input,
            quantity=baseline_quantity,
            leverage=baseline_leverage,
            margin_usdt=baseline_margin_usdt,
        )
    )
    return FastExitPlan(exit_result, sizing)
