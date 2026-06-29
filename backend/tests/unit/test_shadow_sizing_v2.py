from dataclasses import replace
from decimal import Decimal

import pytest

from agents.shadow.exchange_rules import SHADOW_SYMBOL_RULES
from agents.shadow.pnl import ShadowCostConfig
from agents.shadow.sizing import (
    ShadowSizingInput,
    size_from_risk_budget,
    worst_loss_per_coin,
)


def _input(direction: str = "LONG", **overrides) -> ShadowSizingInput:
    values = dict(
        direction=direction,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49500") if direction == "LONG" else Decimal("50500"),
        take_profit=Decimal("51000") if direction == "LONG" else Decimal("49000"),
        equity_usdt=Decimal("10000"),
        available_balance_usdt=Decimal("10000"),
        risk_per_trade_pct=Decimal("0.01"),
        open_strategy_risk_usdt=Decimal("0"),
        max_portfolio_risk_pct=Decimal("0.10"),
        max_single_position_margin_ratio=Decimal("0.20"),
        margin_buffer_ratio=Decimal("1.10"),
        plan_max_leverage=10,
        user_max_leverage=10,
        system_max_leverage=20,
        shadow_safe_leverage_cap=5,
        funding_intervals=1,
        symbol_rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
        cost_config=ShadowCostConfig(),
    )
    values.update(overrides)
    return ShadowSizingInput(**values)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_long_and_short_sizing_obey_risk_budget(direction):
    inp = _input(direction)
    result = size_from_risk_budget(inp)
    assert result.approved
    assert result.actual_max_loss_usdt <= result.risk_budget_usdt
    assert result.quantity % inp.symbol_rules.quantity_step == 0
    assert 1 <= result.leverage <= 5


def test_short_sl_uses_higher_exit_notional_for_costs():
    long_loss = worst_loss_per_coin(_input("LONG"))
    short_loss = worst_loss_per_coin(_input("SHORT"))
    assert short_loss > long_loss


def test_narrow_sl_still_includes_round_trip_costs_and_funding():
    inp = _input(stop_loss=Decimal("49990"))
    assert worst_loss_per_coin(inp) > Decimal("10")


def test_wide_sl_reduces_quantity():
    narrow = size_from_risk_budget(_input(stop_loss=Decimal("49900")))
    wide = size_from_risk_budget(_input(stop_loss=Decimal("45000")))
    assert narrow.approved and wide.approved
    assert wide.quantity < narrow.quantity


def test_quantity_is_reduced_to_leverage_cap_without_exceeding_budget():
    result = size_from_risk_budget(
        _input(
            max_single_position_margin_ratio=Decimal("0.01"),
            shadow_safe_leverage_cap=2,
        )
    )
    assert result.approved
    assert result.leverage <= 2
    assert result.actual_max_loss_usdt <= result.risk_budget_usdt
    assert "quantity reduced" in result.leverage_reason


def test_insufficient_risk_budget_rejects_minimum_quantity():
    result = size_from_risk_budget(
        _input(equity_usdt=Decimal("1"), available_balance_usdt=Decimal("1"))
    )
    assert not result.approved
    assert result.rejection_code == "MIN_QUANTITY"


def test_portfolio_risk_isolated_ledger_limit_rejects():
    result = size_from_risk_budget(
        _input(
            open_strategy_risk_usdt=Decimal("999"),
            max_portfolio_risk_pct=Decimal("0.10"),
        )
    )
    assert not result.approved
    assert result.rejection_code == "PORTFOLIO_RISK_EXCEEDED"


def test_result_is_deterministic_and_has_no_confidence_input():
    inp = _input()
    assert size_from_risk_budget(inp) == size_from_risk_budget(replace(inp))


def test_float_decimal_boundary_is_rejected_without_implicit_coercion():
    with pytest.raises(TypeError):
        worst_loss_per_coin(_input(entry_price=50000.0))  # type: ignore[arg-type]
