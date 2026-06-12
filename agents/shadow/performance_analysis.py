"""Shadow decision-log performance analysis.

Reads Step 14 decision logs from JSONL or app log lines containing
``decision_log {json}`` and returns a JSON-serializable summary.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

STRATEGY_TYPES = ("SCALPING", "INTRADAY", "TREND_FOLLOWING", "BREAKOUT")
AI_CONFIDENCE_BUCKETS = ("60-70", "70-80", "80-90", "90-100", "UNKNOWN")


@dataclass
class ParsedDecisionLogs:
    records: list[dict[str, Any]]
    invalid_lines: int = 0


def load_decision_logs(path: str | Path) -> ParsedDecisionLogs:
    """Load JSONL decision logs, skipping invalid lines safely."""
    records: list[dict[str, Any]] = []
    invalid = 0
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            parsed = _parse_line(line)
            if parsed is None:
                if line.strip():
                    invalid += 1
                continue
            records.append(parsed)
    return ParsedDecisionLogs(records=records, invalid_lines=invalid)


def analyze_log_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    parsed = load_decision_logs(input_path)
    summary = analyze_decision_logs(parsed.records, invalid_lines=parsed.invalid_lines)
    if output_path is not None:
        save_summary(summary, output_path)
    return summary


def analyze_decision_logs(
    records: Iterable[dict[str, Any]],
    *,
    invalid_lines: int = 0,
) -> dict[str, Any]:
    rows = [r for r in records if isinstance(r, dict)]
    trade_results = [_trade_result(r) for r in rows]
    closed = [t for t in trade_results if t is not None and t["closed"]]

    rejection_counts = Counter(
        str(r.get("rejection_reason") or "UNKNOWN")
        for r in rows
        if (r.get("final_action") == "HOLD" or r.get("rejection_reason"))
    )

    net_values = [t["net_pnl"] for t in closed]
    gross_values = [t["gross_pnl"] for t in closed]
    wins = [p for p in net_values if p > 0]
    losses = [p for p in net_values if p < 0]

    summary = {
        "total_candidates": len(rows),
        "executed_trades": sum(1 for t in trade_results if t is not None and t["executed"]),
        "closed_trades": len(closed),
        "hold_count": sum(1 for r in rows if r.get("final_action") == "HOLD"),
        "rejection_reasons": dict(rejection_counts),
        "invalid_lines_skipped": invalid_lines,
        "win_rate": _ratio(len(wins), len(closed)),
        "net_pnl_after_fees_slippage": round(sum(net_values), 8),
        "gross_pnl": round(sum(gross_values), 8),
        "fee_impact": round(sum(_num(r.get("expected_fees")) for r in rows), 8),
        "slippage_impact": round(
            sum(_num(r.get("expected_slippage_cost")) for r in rows),
            8,
        ),
        "profit_factor": _profit_factor(net_values),
        "max_drawdown": _max_drawdown(net_values),
        "average_win": _average(wins),
        "average_loss": _average(losses),
        "average_holding_time": _average(
            [_holding_minutes(r) for r in rows if _holding_minutes(r) is not None]
        ),
        "max_consecutive_losses": _max_consecutive_losses(net_values),
        "performance_by_market_regime": _group_performance(rows, "market_regime"),
        "performance_by_strategy_type": _strategy_performance(rows),
        "performance_by_direction": _group_performance(rows, "candidate_action"),
        "performance_by_ai_confidence_bucket": _ai_confidence_performance(rows),
        "performance_by_rr_bucket": _bucket_performance(rows, _rr_bucket),
        "performance_by_spread_bucket": _bucket_performance(rows, _spread_bucket),
        "performance_by_funding_condition": _bucket_performance(rows, _funding_bucket),
    }
    summary["warnings"] = _warnings(summary)
    return summary


def save_summary(summary: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def format_human_summary(summary: dict[str, Any]) -> str:
    warnings = summary.get("warnings") or []
    lines = [
        "Shadow Performance Summary",
        f"Total candidates: {summary.get('total_candidates', 0)}",
        f"Executed trades: {summary.get('executed_trades', 0)}",
        f"HOLD count: {summary.get('hold_count', 0)}",
        f"Win rate: {summary.get('win_rate', 0):.2%}",
        f"Net PnL after fees/slippage: {summary.get('net_pnl_after_fees_slippage', 0):.2f}",
        f"Gross PnL: {summary.get('gross_pnl', 0):.2f}",
        f"Profit factor: {summary.get('profit_factor', 0):.2f}",
        f"Max drawdown: {summary.get('max_drawdown', 0):.2f}",
        f"Invalid lines skipped: {summary.get('invalid_lines_skipped', 0)}",
    ]
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {w}" for w in warnings)
    return "\n".join(lines)


def _parse_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    if "decision_log " in text:
        text = text.split("decision_log ", 1)[1].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _trade_result(row: dict[str, Any]) -> dict[str, Any] | None:
    action = row.get("final_action") or row.get("candidate_action")
    actual = row.get("actual_result") or {}
    executed = bool(actual.get("executed"))
    if action not in {"LONG", "SHORT"} and not executed:
        return None

    net = _first_num(
        actual,
        ("net_pnl", "net_pnl_usdt", "realized_net_pnl", "pnl_usdt", "realized_pnl_usdt"),
    )
    gross = _first_num(actual, ("gross_pnl", "gross_pnl_usdt", "realized_gross_pnl"))
    status = str(actual.get("status") or actual.get("result") or "").upper()

    if net is None:
        if status in {"TP_HIT", "WIN", "PROFIT"}:
            net = _num(row.get("expected_net_profit"))
        elif status in {"SL_HIT", "LOSS"}:
            net = -_num(row.get("expected_net_loss"))
    if gross is None:
        if status in {"TP_HIT", "WIN", "PROFIT"}:
            gross = _num(row.get("expected_gross_profit"))
        elif status in {"SL_HIT", "LOSS"}:
            gross = -_num(row.get("expected_gross_loss"))

    closed = net is not None
    return {
        "executed": executed,
        "closed": closed,
        "net_pnl": net or 0.0,
        "gross_pnl": gross if gross is not None else (net or 0.0),
    }


def _group_performance(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get(field) or "UNKNOWN")
        groups.setdefault(key, []).append(row)
    return {key: _summarize_group(value) for key, value in sorted(groups.items())}


def _strategy_performance(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped = _group_performance(rows, "strategy_type")
    for strategy in STRATEGY_TYPES:
        grouped.setdefault(strategy, _summarize_group([]))
    return {key: grouped[key] for key in sorted(grouped)}


def _ai_confidence_performance(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped = _bucket_performance(rows, _ai_bucket)
    for bucket in AI_CONFIDENCE_BUCKETS:
        grouped.setdefault(bucket, _summarize_group([]))
    return {key: grouped[key] for key in AI_CONFIDENCE_BUCKETS}


def _bucket_performance(
    rows: list[dict[str, Any]],
    bucket_fn: Any,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(bucket_fn(row), []).append(row)
    return {key: _summarize_group(value) for key, value in sorted(groups.items())}


def _summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [_trade_result(r) for r in rows]
    closed = [r for r in results if r is not None and r["closed"]]
    net = [r["net_pnl"] for r in closed]
    wins = [p for p in net if p > 0]
    losses = [p for p in net if p < 0]
    return {
        "total_candidates": len(rows),
        "executed_trades": sum(1 for r in results if r is not None and r["executed"]),
        "closed_trades": len(closed),
        "win_rate": _ratio(len(wins), len(closed)),
        "net_pnl_after_fees_slippage": round(sum(net), 8),
        "gross_pnl": round(sum(r["gross_pnl"] for r in closed), 8),
        "profit_factor": _profit_factor(net),
        "average_win": _average(wins),
        "average_loss": _average(losses),
    }


def _warnings(summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    net = _num(summary.get("net_pnl_after_fees_slippage"))
    gross = abs(_num(summary.get("gross_pnl")))
    fee = abs(_num(summary.get("fee_impact")))
    slippage = abs(_num(summary.get("slippage_impact")))

    if net <= 0:
        warnings.append("Net PnL <= 0. Not ready for live trading.")
    if _num(summary.get("profit_factor")) < 1.2:
        warnings.append("Profit factor < 1.2. Not ready for live trading.")
    if _ai_confidence_not_calibrated(summary):
        warnings.append(
            "AI confidence is not calibrated. Do not use this threshold for live trading yet."
        )
    for strategy, perf in summary.get("performance_by_strategy_type", {}).items():
        if perf.get("closed_trades", 0) >= 2 and perf.get("net_pnl_after_fees_slippage", 0) < 0:
            warnings.append(f"{strategy} is consistently negative. Disable or retune it.")
    if gross > 0 and (fee + slippage) / gross >= 0.30:
        warnings.append("Fees/slippage consume too much gross PnL. Watch overtrading or targets.")
    return warnings


def _ai_confidence_not_calibrated(summary: dict[str, Any]) -> bool:
    buckets = summary.get("performance_by_ai_confidence_bucket", {})
    ordered = [
        buckets.get(bucket, {}).get("net_pnl_after_fees_slippage")
        for bucket in ("60-70", "70-80", "80-90", "90-100")
        if buckets.get(bucket, {}).get("closed_trades", 0) > 0
    ]
    if len(ordered) < 2:
        return False
    return any(float(ordered[i]) > float(ordered[i + 1]) for i in range(len(ordered) - 1))


def _ai_bucket(row: dict[str, Any]) -> str:
    confidence = _num((row.get("ai_review") or {}).get("confidence"))
    pct = confidence * 100 if confidence <= 1 else confidence
    if 60 <= pct < 70:
        return "60-70"
    if 70 <= pct < 80:
        return "70-80"
    if 80 <= pct < 90:
        return "80-90"
    if 90 <= pct <= 100:
        return "90-100"
    return "UNKNOWN"


def _rr_bucket(row: dict[str, Any]) -> str:
    rr = _num(row.get("actual_rr"))
    if rr <= 0:
        return "UNKNOWN"
    if rr < 1.5:
        return "<1.5"
    if rr < 2.0:
        return "1.5-2.0"
    if rr < 3.0:
        return "2.0-3.0"
    return ">=3.0"


def _spread_bucket(row: dict[str, Any]) -> str:
    spread = _num(row.get("spread_bps"))
    if spread <= 0:
        return "UNKNOWN"
    if spread <= 2:
        return "0-2bps"
    if spread <= 5:
        return "2-5bps"
    if spread <= 10:
        return "5-10bps"
    return ">10bps"


def _funding_bucket(row: dict[str, Any]) -> str:
    funding = row.get("funding_rate")
    if funding is None:
        funding = row.get("funding_cost")
    value = _num(funding)
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    if funding is not None:
        return "NEUTRAL"
    return "UNKNOWN"


def _holding_minutes(row: dict[str, Any]) -> float | None:
    for key in ("holding_time", "expected_holding_minutes"):
        value = row.get(key)
        if value is not None:
            return _num(value)
    actual = row.get("actual_result") or {}
    value = actual.get("holding_time") or actual.get("holding_minutes")
    if value is not None:
        return _num(value)
    return None


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 8)


def _max_consecutive_losses(values: list[float]) -> int:
    current = 0
    best = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _profit_factor(values: list[float]) -> float:
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if gains <= 0:
        return 0.0
    if losses <= 0:
        return round(gains, 8)
    return round(gains / losses, 8)


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 8) if values else 0.0


def _ratio(num: int, den: int) -> float:
    return round(num / den, 8) if den else 0.0


def _first_num(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if data.get(key) is not None:
            return _num(data[key])
    return None


def _num(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
