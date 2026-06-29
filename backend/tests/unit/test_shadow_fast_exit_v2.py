from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

import pytest

from agents.shadow.exchange_rules import SHADOW_SYMBOL_RULES
from agents.shadow.pnl import ShadowCostConfig
from agents.shadow.strategies.fast_exit_v2 import FastExitConfig, build_fast_exit


class Action(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Candidate:
    action: Action
    coin: str
    symbol: str
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    expected_holding_minutes: int = 60
    actual_rr: float = 2.0
    reasons: list[str] = field(default_factory=list)


def _config(**overrides) -> FastExitConfig:
    values = dict(
        tp_pct=Decimal("0.006"),
        sl_pct=Decimal("0.003"),
        min_sl_pct=Decimal("0.0025"),
        max_hold_seconds=900,
        min_rr=Decimal("2"),
        min_tp_cost_multiple=Decimal("1"),
    )
    values.update(overrides)
    return FastExitConfig(**values)


def _candidate(action: Action = Action.LONG) -> Candidate:
    return Candidate(
        action=action,
        coin="BTC",
        symbol="BTCUSDT",
        entry_price=Decimal("50000"),
        take_profit=Decimal("51000") if action == Action.LONG else Decimal("49000"),
        stop_loss=Decimal("49500") if action == Action.LONG else Decimal("50500"),
        reasons=["source"],
    )


@pytest.mark.parametrize(
    ("action", "expected_tp", "expected_sl"),
    [
        (Action.LONG, Decimal("50300"), Decimal("49850")),
        (Action.SHORT, Decimal("49700"), Decimal("50150")),
    ],
)
def test_fast_exit_long_and_short(action, expected_tp, expected_sl):
    result = build_fast_exit(
        _candidate(action),
        config=_config(),
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert result.approved
    assert result.candidate.take_profit == expected_tp
    assert result.candidate.stop_loss == expected_sl
    assert result.candidate.actual_rr == pytest.approx(2.0)


def test_source_candidate_is_not_mutated():
    source = _candidate()
    original = (source.take_profit, source.stop_loss, list(source.reasons))
    result = build_fast_exit(
        source,
        config=_config(),
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert result.candidate is not source
    assert (source.take_profit, source.stop_loss, source.reasons) == original


def test_minimum_sl_distance_can_reject_rr_instead_of_silently_narrowing():
    result = build_fast_exit(
        _candidate(),
        config=_config(min_sl_pct=Decimal("0.005")),
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert not result.approved
    assert result.rejection_code == "MIN_RR_NOT_MET"


def test_high_cost_rejects_unprofitable_tp():
    result = build_fast_exit(
        _candidate(),
        config=_config(),
        cost_config=ShadowCostConfig(
            taker_fee_rate=Decimal("0.01"),
            slippage_bps=Decimal("100"),
            funding_rate_per_interval=Decimal("0.001"),
        ),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert not result.approved
    assert result.rejection_code in {
        "NON_POSITIVE_TP_NET",
        "TP_COST_MULTIPLE_NOT_MET",
    }


def test_unknown_next_funding_uses_at_least_one_interval():
    result = build_fast_exit(
        _candidate(),
        config=_config(max_hold_seconds=60),
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert result.approved
    assert result.funding_intervals == 1


def test_multiple_funding_intervals_use_ceiling():
    result = build_fast_exit(
        _candidate(),
        config=_config(max_hold_seconds=8 * 3600 + 1),
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert result.funding_intervals == 2


def test_float_percentage_is_rejected():
    result = build_fast_exit(
        _candidate(),
        config=_config(tp_pct=0.006),  # type: ignore[arg-type]
        cost_config=ShadowCostConfig(),
        rules=SHADOW_SYMBOL_RULES["BTCUSDT"],
    )
    assert not result.approved
    assert result.rejection_code == "DECIMAL_REQUIRED"
