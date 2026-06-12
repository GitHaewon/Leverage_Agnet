from __future__ import annotations

import json

import pytest

from scripts.run_shadow_smoke import main, run_smoke
from agents.shadow.performance_analysis import analyze_log_file


@pytest.mark.asyncio
async def test_run_shadow_smoke_writes_required_jsonl(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    output = tmp_path / "shadow_smoke.jsonl"

    payload = await run_smoke("BTCUSDT", output, use_real_ai=False)

    assert output.exists()
    row = json.loads(output.read_text(encoding="utf-8").strip())
    for key in (
        "timestamp",
        "symbol",
        "final_action",
        "strategy_type",
        "expected_net_profit",
        "expected_fees",
        "expected_slippage_cost",
        "actual_rr",
        "ai_review",
        "risk_result",
        "risk_failed_checks",
        "rejection_reason",
    ):
        assert key in row

    assert payload["symbol"] == "BTCUSDT"
    assert row["actual_result"]["mode"] == "paper"
    assert row["actual_result"]["executed"] is True
    assert row["ai_review"]["review_action"] == "APPROVE"


@pytest.mark.asyncio
async def test_run_shadow_smoke_refuses_live_trading(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED=true"):
        await run_smoke("BTCUSDT", tmp_path / "shadow_smoke.jsonl")


def test_main_refuses_live_trading(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

    code = main(["--output", str(tmp_path / "shadow_smoke.jsonl")])

    captured = capsys.readouterr()
    assert code == 2
    assert "Refusing to run" in captured.err


@pytest.mark.asyncio
async def test_include_closed_samples_exercises_analyzer_metrics(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    output = tmp_path / "shadow_smoke_samples.jsonl"

    payload = await run_smoke(
        "BTCUSDT",
        output,
        use_real_ai=False,
        include_closed_samples=True,
    )

    rows = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert payload["closed_samples_written"] == 4
    assert len(rows) == 5

    summary = analyze_log_file(output)
    assert summary["closed_trades"] == 3
    assert summary["win_rate"] == pytest.approx(2 / 3)
    assert summary["net_pnl_after_fees_slippage"] == pytest.approx(130)
    assert summary["gross_pnl"] == pytest.approx(170)
    assert summary["profit_factor"] == pytest.approx(3.6)
    assert summary["max_drawdown"] == pytest.approx(50)
    assert summary["average_win"] == pytest.approx(90)
    assert summary["average_loss"] == pytest.approx(-50)
    assert summary["rejection_reasons"]["sample HOLD rejection: insufficient confluence"] == 1

    by_direction = summary["performance_by_direction"]
    assert by_direction["LONG"]["closed_trades"] == 2
    assert by_direction["LONG"]["win_rate"] == pytest.approx(0.5)
    assert by_direction["SHORT"]["closed_trades"] == 1
    assert by_direction["SHORT"]["win_rate"] == pytest.approx(1.0)

    by_strategy = summary["performance_by_strategy_type"]
    assert by_strategy["TREND_FOLLOWING"]["closed_trades"] == 2
    assert by_strategy["TREND_FOLLOWING"]["net_pnl_after_fees_slippage"] == pytest.approx(50)
    assert by_strategy["BREAKOUT"]["closed_trades"] == 1
    assert by_strategy["BREAKOUT"]["net_pnl_after_fees_slippage"] == pytest.approx(80)
