from __future__ import annotations

import json

from agents.shadow.performance_analysis import (
    analyze_decision_logs,
    analyze_log_file,
    load_decision_logs,
)


def _row(
    *,
    action: str = "LONG",
    net_pnl: float | None = 10.0,
    gross_pnl: float | None = 14.0,
    strategy: str = "SCALPING",
    confidence: float = 0.85,
    rejection_reason: str | None = None,
    status: str | None = None,
    rr: float = 1.8,
    spread: float = 1.5,
) -> dict:
    actual = {"executed": action in {"LONG", "SHORT"}, "status": status or "CLOSED"}
    if net_pnl is not None:
        actual["net_pnl"] = net_pnl
    if gross_pnl is not None:
        actual["gross_pnl"] = gross_pnl
    return {
        "timestamp": "2026-06-12T00:00:00+00:00",
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "market_price": 67000,
        "expected_entry_price": 67000,
        "simulated_fill_price": 67000,
        "market_regime": "TRENDING",
        "strategy_type": strategy,
        "expected_holding_minutes": 30,
        "actual_rr": rr,
        "min_required_rr": 1.2,
        "ai_review": {"confidence": confidence, "review_action": "APPROVE"},
        "risk_failed_checks": [],
        "candidate_action": action,
        "final_action": action,
        "rejection_reason": rejection_reason,
        "spread_bps": spread,
        "slippage_bps": 2.0,
        "funding_rate": -0.0001,
        "expected_gross_profit": 14.0,
        "expected_gross_loss": 8.0,
        "expected_fees": 2.0,
        "expected_slippage_cost": 2.0,
        "expected_net_profit": 10.0,
        "expected_net_loss": 12.0,
        "actual_result": actual,
    }


def test_empty_log_returns_safe_zero_summary() -> None:
    summary = analyze_decision_logs([])
    assert summary["total_candidates"] == 0
    assert summary["executed_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["net_pnl_after_fees_slippage"] == 0


def test_invalid_log_lines_are_skipped(tmp_path) -> None:
    path = tmp_path / "decisions.log"
    path.write_text(
        "\n".join([
            "not json",
            json.dumps(_row()),
            "INFO decision_log " + json.dumps(_row(action="HOLD", rejection_reason="no trade")),
        ]),
        encoding="utf-8",
    )
    parsed = load_decision_logs(path)
    summary = analyze_log_file(path)

    assert parsed.invalid_lines == 1
    assert summary["invalid_lines_skipped"] == 1
    assert summary["total_candidates"] == 2


def test_net_pnl_after_fees_slippage_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(net_pnl=10, gross_pnl=14),
        _row(action="SHORT", net_pnl=-6, gross_pnl=-4),
    ])
    assert summary["net_pnl_after_fees_slippage"] == 4
    assert summary["gross_pnl"] == 10
    assert summary["fee_impact"] == 4
    assert summary["slippage_impact"] == 4


def test_win_rate_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(net_pnl=10),
        _row(action="SHORT", net_pnl=-5),
    ])
    assert summary["win_rate"] == 0.5


def test_profit_factor_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(net_pnl=12),
        _row(action="SHORT", net_pnl=-4),
    ])
    assert summary["profit_factor"] == 3.0


def test_max_drawdown_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(net_pnl=10),
        _row(action="SHORT", net_pnl=-3),
        _row(net_pnl=-4),
        _row(action="SHORT", net_pnl=5),
    ])
    assert summary["max_drawdown"] == 7
    assert summary["max_consecutive_losses"] == 2


def test_rejection_reasons_are_counted() -> None:
    summary = analyze_decision_logs([
        _row(action="HOLD", net_pnl=None, gross_pnl=None, rejection_reason="AI reject"),
        _row(action="HOLD", net_pnl=None, gross_pnl=None, rejection_reason="AI reject"),
        _row(action="HOLD", net_pnl=None, gross_pnl=None, rejection_reason="Risk reject"),
    ])
    assert summary["hold_count"] == 3
    assert summary["rejection_reasons"]["AI reject"] == 2
    assert summary["rejection_reasons"]["Risk reject"] == 1


def test_performance_by_strategy_type_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(strategy="SCALPING", net_pnl=10),
        _row(strategy="INTRADAY", net_pnl=-5),
    ])
    assert summary["performance_by_strategy_type"]["SCALPING"]["net_pnl_after_fees_slippage"] == 10
    assert summary["performance_by_strategy_type"]["INTRADAY"]["net_pnl_after_fees_slippage"] == -5
    assert "TREND_FOLLOWING" in summary["performance_by_strategy_type"]
    assert "BREAKOUT" in summary["performance_by_strategy_type"]


def test_performance_by_ai_confidence_bucket_is_calculated() -> None:
    summary = analyze_decision_logs([
        _row(confidence=0.65, net_pnl=5),
        _row(confidence=0.75, net_pnl=7),
        _row(confidence=0.95, net_pnl=-2),
    ])
    buckets = summary["performance_by_ai_confidence_bucket"]
    assert buckets["60-70"]["net_pnl_after_fees_slippage"] == 5
    assert buckets["70-80"]["net_pnl_after_fees_slippage"] == 7
    assert buckets["90-100"]["net_pnl_after_fees_slippage"] == -2


def test_warning_is_generated_when_net_pnl_non_positive() -> None:
    summary = analyze_decision_logs([_row(net_pnl=-1)])
    assert any("Net PnL <= 0" in warning for warning in summary["warnings"])


def test_warning_is_generated_when_profit_factor_below_threshold() -> None:
    summary = analyze_decision_logs([
        _row(net_pnl=10),
        _row(action="SHORT", net_pnl=-9),
    ])
    assert any("Profit factor < 1.2" in warning for warning in summary["warnings"])


def test_machine_readable_summary_is_saved(tmp_path) -> None:
    input_path = tmp_path / "decisions.jsonl"
    output_path = tmp_path / "summary.json"
    input_path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")

    summary = analyze_log_file(input_path, output_path)
    saved = json.loads(output_path.read_text(encoding="utf-8"))

    assert saved["total_candidates"] == 1
    assert saved["net_pnl_after_fees_slippage"] == summary["net_pnl_after_fees_slippage"]
