from __future__ import annotations

import pytest

from scripts.analyze_shadow_db import build_trade_metrics


def test_trade_metrics_returns_no_performance_when_no_trades() -> None:
    summary = {
        "total": 0,
        "open_trades": 0,
        "closed_trades": 0,
        "wins": 0,
        "gross_pnl": 0,
        "gross_profit": 0,
        "gross_loss": 0,
        "net_pnl": 0,
        "fees": 0,
        "funding": 0,
        "slippage": 0,
    }

    metrics = build_trade_metrics(summary, [], [])

    assert metrics["performance_status"] == "성과 판단 불가"
    assert metrics["win_rate"] is None
    assert metrics["gross_pnl"] is None


def test_trade_metrics_calculates_closed_trade_performance() -> None:
    summary = {
        "total": 3,
        "open_trades": 1,
        "closed_trades": 2,
        "wins": 1,
        "gross_pnl": 60.0,
        "gross_profit": 100.0,
        "gross_loss": -40.0,
        "net_pnl": 57.5,
        "fees": 1.5,
        "funding": 0.25,
        "slippage": 0.75,
    }
    rr_rows = [
        {"direction": "LONG", "entry_price": 100, "tp_price": 120, "sl_price": 90},
        {"direction": "SHORT", "entry_price": 100, "tp_price": 80, "sl_price": 110},
    ]
    pnl_rows = [{"pnl": 100.0}, {"pnl": -40.0}]

    metrics = build_trade_metrics(summary, rr_rows, pnl_rows)

    assert metrics["open_trades"] == 1
    assert metrics["closed_trades"] == 2
    assert metrics["win_rate"] == pytest.approx(50.0)
    assert metrics["gross_pnl"] == pytest.approx(60.0)
    assert metrics["net_pnl"] == pytest.approx(57.5)
    assert metrics["fees"] == pytest.approx(1.5)
    assert metrics["funding"] == pytest.approx(0.25)
    assert metrics["slippage"] == pytest.approx(0.75)
    assert metrics["fees_slippage_reflected"] is True
    assert metrics["profit_factor"] == pytest.approx(2.5)
    assert metrics["max_drawdown"] == pytest.approx(40.0)
    assert metrics["average_rr"] == pytest.approx(2.0)
