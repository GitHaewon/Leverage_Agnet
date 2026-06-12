from __future__ import annotations

import json

import pytest

from scripts.run_shadow_smoke import main, run_smoke


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
