from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.shadow.pnl import ShadowCostConfig, calculate_shadow_pnl, gross_pnl
from agents.shadow.models import ShadowTradeRecord

UTC = timezone.utc
OPENED = datetime(2026, 6, 29, 0, 1, tzinfo=UTC)
CLOSED = datetime(2026, 6, 29, 7, 59, tzinfo=UTC)


def _calculate(
    direction: str,
    entry: str,
    exit_: str,
    config: ShadowCostConfig,
    margin: str = "50",
):
    return calculate_shadow_pnl(
        direction=direction,
        entry_price=Decimal(entry),
        exit_price=Decimal(exit_),
        quantity=Decimal("2"),
        margin_usdt=Decimal(margin),
        opened_at=OPENED,
        closed_at=CLOSED,
        config=config,
    )


@pytest.mark.parametrize(
    ("direction", "entry", "exit_", "expected"),
    [
        ("LONG", "100", "110", Decimal("20")),
        ("SHORT", "100", "90", Decimal("20")),
        ("LONG", "100", "90", Decimal("-20")),
        ("SHORT", "100", "110", Decimal("-20")),
    ],
)
def test_gross_pnl_long_and_short(direction, entry, exit_, expected):
    assert gross_pnl(direction, Decimal(entry), Decimal(exit_), Decimal("2")) == expected


def test_zero_cost_preserves_gross_as_net():
    result = _calculate(
        "LONG",
        "100",
        "110",
        ShadowCostConfig(
            taker_fee_rate=Decimal("0"),
            slippage_bps=Decimal("0"),
            funding_rate_per_interval=Decimal("0"),
        ),
    )
    assert result.gross_pnl_usdt == Decimal("20.00000000")
    assert result.net_pnl_usdt == Decimal("20.00000000")
    assert result.net_return_on_margin_pct == Decimal("40.0000")


def test_normal_taker_costs_long():
    result = _calculate("LONG", "100", "110", ShadowCostConfig())
    assert result.entry_fee_usdt == Decimal("0.08004000")
    assert result.exit_fee_usdt == Decimal("0.08795600")
    assert result.slippage_cost_usdt == Decimal("0.21000000")
    assert result.funding_fee_usdt == Decimal("0")
    assert result.net_pnl_usdt == Decimal("19.62200400")
    assert result.net_return_on_margin_pct == Decimal("39.2440")


def test_exit_slippage_is_independently_present_in_net_expectation():
    result = _calculate("LONG", "100", "110", ShadowCostConfig())
    expected = (
        result.gross_pnl_usdt
        - result.entry_fee_usdt
        - result.exit_fee_usdt
        - result.funding_fee_usdt
        - result.entry_slippage_usdt
        - result.exit_slippage_usdt
    )
    without_exit_slippage = expected + result.exit_slippage_usdt
    assert result.exit_slippage_usdt == Decimal("0.11000000")
    assert result.net_pnl_usdt == expected
    assert result.net_pnl_usdt != without_exit_slippage


def test_normal_taker_costs_short():
    result = _calculate("SHORT", "100", "90", ShadowCostConfig())
    assert result.entry_fee_usdt == Decimal("0.07996000")
    assert result.exit_fee_usdt == Decimal("0.07203600")
    assert result.slippage_cost_usdt == Decimal("0.19000000")
    assert result.net_pnl_usdt == Decimal("19.65800400")


def test_large_costs_can_materially_reduce_net_pnl():
    result = _calculate(
        "LONG",
        "100",
        "110",
        ShadowCostConfig(
            taker_fee_rate=Decimal("0.01"),
            slippage_bps=Decimal("100"),
            funding_rate_per_interval=Decimal("0"),
        ),
    )
    assert result.entry_fee_usdt == Decimal("2.02000000")
    assert result.exit_fee_usdt == Decimal("2.17800000")
    assert result.slippage_cost_usdt == Decimal("4.20000000")
    assert result.net_pnl_usdt == Decimal("11.60200000")


def test_positive_funding_costs_long_and_credits_short():
    close_at_funding = datetime(2026, 6, 29, 8, 0, tzinfo=UTC)
    config = ShadowCostConfig(
        taker_fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
        funding_rate_per_interval=Decimal("0.001"),
    )
    common = dict(
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        quantity=Decimal("2"),
        margin_usdt=Decimal("50"),
        opened_at=OPENED,
        closed_at=close_at_funding,
        config=config,
    )
    long_result = calculate_shadow_pnl(direction="LONG", **common)
    short_result = calculate_shadow_pnl(direction="SHORT", **common)
    assert long_result.funding_fee_usdt == Decimal("0.20000000")
    assert long_result.net_pnl_usdt == Decimal("-0.20000000")
    assert short_result.funding_fee_usdt == Decimal("-0.20000000")
    assert short_result.net_pnl_usdt == Decimal("0.20000000")


def test_leverage_does_not_multiply_amount_pnl():
    config = ShadowCostConfig(
        taker_fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
        funding_rate_per_interval=Decimal("0"),
    )
    low_leverage = _calculate("LONG", "100", "110", config, margin="100")
    high_leverage = _calculate("LONG", "100", "110", config, margin="25")
    assert low_leverage.net_pnl_usdt == high_leverage.net_pnl_usdt
    assert low_leverage.net_return_on_margin_pct == Decimal("20.0000")
    assert high_leverage.net_return_on_margin_pct == Decimal("80.0000")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"taker_fee_rate": Decimal("-0.1")},
        {"slippage_bps": Decimal("-1")},
        {"funding_interval_hours": 7},
    ],
)
def test_invalid_cost_settings_fail_explicitly(kwargs):
    with pytest.raises(ValueError):
        ShadowCostConfig(**kwargs)


@pytest.mark.parametrize(
    ("exit_status", "exit_price"),
    [
        ("TP_HIT", Decimal("110")),
        ("SL_HIT", Decimal("90")),
        ("MAX_HOLD", Decimal("105")),
    ],
)
def test_shadow_trade_close_uses_single_cost_formula_for_exit_reasons(
    exit_status,
    exit_price,
):
    config = ShadowCostConfig()
    trade = ShadowTradeRecord.open(
        user_id="user-1",
        coin="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("100"),
        tp_price=Decimal("110"),
        sl_price=Decimal("90"),
        quantity=Decimal("2"),
        leverage=5,
        margin_usdt=Decimal("50"),
        opened_at=OPENED,
    )

    expected = calculate_shadow_pnl(
        direction=trade.direction,
        entry_price=trade.entry_price,
        exit_price=exit_price,
        quantity=trade.quantity,
        margin_usdt=trade.margin_usdt,
        opened_at=trade.opened_at,
        closed_at=CLOSED,
        config=config,
    )

    trade.close(exit_price, exit_status, closed_at=CLOSED, cost_config=config)

    assert trade.gross_pnl_usdt == expected.gross_pnl_usdt
    assert trade.entry_fee_usdt == expected.entry_fee_usdt
    assert trade.exit_fee_usdt == expected.exit_fee_usdt
    assert trade.entry_slippage_usdt == expected.entry_slippage_usdt
    assert trade.exit_slippage_usdt == expected.exit_slippage_usdt
    assert trade.estimated_slippage_usdt == expected.slippage_cost_usdt
    assert trade.funding_fee_usdt == expected.funding_fee_usdt
    assert trade.net_pnl_usdt == expected.net_pnl_usdt
    assert trade.pnl_calculation_status == "COST_ADJUSTED"
