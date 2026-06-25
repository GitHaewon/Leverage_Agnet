"""Shadow decision-log performance analysis.

Reads Step 14 decision logs from JSONL or app log lines containing
``decision_log {json}``. It also accepts JSONL exported from the
``shadow_decisions`` table and normalizes it into the decision-log shape.
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
    rows = [_normalize_record(r) for r in records if isinstance(r, dict)]
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
    total_decisions = len(rows)
    executed_trades = sum(
        1 for t in trade_results if t is not None and t["executed"]
    )
    hold_count = sum(1 for r in rows if r.get("final_action") == "HOLD")

    summary = {
        "total_decisions": total_decisions,
        "total_candidates": total_decisions,  # backward-compatible alias
        "executed_trades": executed_trades,
        "closed_trades": len(closed),
        "hold_count": hold_count,
        "hold_rate": _ratio(hold_count, total_decisions),
        "rejection_reasons": dict(rejection_counts),
        "rejection_reason_top10": _top_counter(rejection_counts, 10),
        "rejection_stage_distribution": _stage_distribution(rows),
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
        "market_regime_execution_rate": _execution_rate_by(rows, "market_regime"),
        "strategy_type_execution_rate": _execution_rate_by(rows, "strategy_type"),
        "chart_score_distribution": _chart_score_distribution(rows),
        "ai_reject_rate": _ai_reject_rate(rows),
        "risk_reject_code_distribution": _risk_reject_code_distribution(rows),
    }
    summary["warnings"] = _warnings(summary)
    summary["diagnosis"] = _diagnose_zero_trades(rows, summary)
    return summary


def save_summary(summary: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def format_human_summary(summary: dict[str, Any]) -> str:
    warnings = summary.get("warnings") or []
    diagnosis = summary.get("diagnosis") or {}
    lines = [
        "Shadow Trading 의사결정 분석 요약",
        f"- 전체 decision 수: {summary.get('total_decisions', 0)}",
        f"- 실행된 가상 거래 수: {summary.get('executed_trades', 0)}",
        f"- HOLD 수 / 비율: {summary.get('hold_count', 0)} / {summary.get('hold_rate', 0):.2%}",
        f"- AI reject rate: {summary.get('ai_reject_rate', 0):.2%}",
        f"- 승률(청산 기준): {summary.get('win_rate', 0):.2%}",
        f"- 수수료/슬리피지 반영 순손익: {summary.get('net_pnl_after_fees_slippage', 0):.2f}",
        f"- 총손익: {summary.get('gross_pnl', 0):.2f}",
        f"- Profit factor: {summary.get('profit_factor', 0):.2f}",
        f"- Max drawdown: {summary.get('max_drawdown', 0):.2f}",
        f"- 무시한 invalid line 수: {summary.get('invalid_lines_skipped', 0)}",
    ]
    stages = summary.get("rejection_stage_distribution") or {}
    if stages:
        lines.append("거절 단계별 비율:")
        for stage, item in stages.items():
            lines.append(
                f"- {stage}: {item.get('count', 0)}건 ({item.get('rate', 0):.2%})"
            )
    reasons = summary.get("rejection_reason_top10") or []
    if reasons:
        lines.append("거절 사유 Top 10:")
        for item in reasons:
            lines.append(
                f"- {item.get('reason')}: {item.get('count', 0)}건 "
                f"({item.get('rate', 0):.2%})"
            )
    if diagnosis:
        lines.append("자동 진단:")
        lines.append(f"- {diagnosis.get('message', '')}")
        for hint in diagnosis.get("hints", []) or []:
            lines.append(f"  - {hint}")
    if warnings:
        lines.append("주의:")
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
    return _normalize_record(value) if isinstance(value, dict) else None


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize decision_log rows and shadow_decisions DB export rows."""
    normalized = dict(row)
    if "expected_entry_price" not in normalized and "expected_entry" in normalized:
        normalized["expected_entry_price"] = normalized.get("expected_entry")
    if "actual_rr" not in normalized and "candidate_rr" in normalized:
        normalized["actual_rr"] = normalized.get("candidate_rr")
    if "leverage" not in normalized and "candidate_leverage" in normalized:
        normalized["leverage"] = normalized.get("candidate_leverage")

    if "ai_review" not in normalized and (
        "ai_decision" in normalized
        or "ai_confidence" in normalized
        or "ai_critical_contradiction" in normalized
    ):
        normalized["ai_review"] = {
            "review_action": normalized.get("ai_decision"),
            "confidence": normalized.get("ai_confidence"),
            "critical_contradiction": normalized.get("ai_critical_contradiction"),
        }

    if "risk_result" not in normalized and (
        "risk_passed" in normalized
        or "risk_reject_reason" in normalized
    ):
        normalized["risk_result"] = {
            "approved": normalized.get("risk_passed"),
            "rejection_reason": normalized.get("risk_reject_reason"),
        }

    if "risk_failed_checks" not in normalized:
        code = (
            normalized.get("risk_rejection_code")
            or normalized.get("rejection_code")
            or normalized.get("risk_code")
        )
        normalized["risk_failed_checks"] = [code] if code else []

    if "actual_result" not in normalized:
        executed = (
            normalized.get("shadow_trade_id") is not None
            or normalized.get("decision_outcome") == "EXECUTED"
            or normalized.get("final_action") in {"LONG", "SHORT"}
            and not normalized.get("rejection_reason")
        )
        normalized["actual_result"] = {"executed": bool(executed)}

    return normalized


def _trade_result(row: dict[str, Any]) -> dict[str, Any] | None:
    action = row.get("final_action") or row.get("candidate_action")
    actual = row.get("actual_result") or {}
    executed = bool(actual.get("executed")) or row.get("decision_outcome") == "EXECUTED"
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
    executed = sum(1 for r in results if r is not None and r["executed"])
    return {
        "total_candidates": len(rows),
        "total_decisions": len(rows),
        "executed_trades": executed,
        "execution_rate": _ratio(executed, len(rows)),
        "hold_rate": _ratio(sum(1 for r in rows if r.get("final_action") == "HOLD"), len(rows)),
        "closed_trades": len(closed),
        "win_rate": _ratio(len(wins), len(closed)),
        "net_pnl_after_fees_slippage": round(sum(net), 8),
        "gross_pnl": round(sum(r["gross_pnl"] for r in closed), 8),
        "profit_factor": _profit_factor(net),
        "average_win": _average(wins),
        "average_loss": _average(losses),
    }


def _execution_rate_by(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped = _group_performance(rows, field)
    return {
        key: {
            "total_decisions": value.get("total_decisions", value.get("total_candidates", 0)),
            "executed_trades": value.get("executed_trades", 0),
            "execution_rate": value.get("execution_rate", 0.0),
            "hold_rate": value.get("hold_rate", 0.0),
        }
        for key, value in grouped.items()
    }


def _stage_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counter = Counter(str(r.get("rejection_stage") or "NONE") for r in rows)
    total = len(rows)
    return {
        stage: {"count": count, "rate": _ratio(count, total)}
        for stage, count in sorted(counter.items())
    }


def _top_counter(counter: Counter, limit: int) -> list[dict[str, Any]]:
    total = sum(counter.values())
    return [
        {"reason": reason, "count": count, "rate": _ratio(count, total)}
        for reason, count in counter.most_common(limit)
    ]


def _chart_score_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: Counter = Counter()
    for row in rows:
        score = _chart_score_value(row.get("chart_score"))
        if score is None:
            buckets["UNKNOWN"] += 1
        elif score < 50:
            buckets["<50"] += 1
        elif score < 60:
            buckets["50-60"] += 1
        elif score < 70:
            buckets["60-70"] += 1
        elif score < 80:
            buckets["70-80"] += 1
        else:
            buckets[">=80"] += 1
    total = len(rows)
    order = ("<50", "50-60", "60-70", "70-80", ">=80", "UNKNOWN")
    return {
        bucket: {"count": buckets.get(bucket, 0), "rate": _ratio(buckets.get(bucket, 0), total)}
        for bucket in order
        if buckets.get(bucket, 0) or bucket == "UNKNOWN"
    }


def _chart_score_value(value: Any) -> float | None:
    if isinstance(value, dict):
        long_score = value.get("long_score")
        short_score = value.get("short_score")
        if long_score is not None or short_score is not None:
            return max(_num(long_score), _num(short_score))
        for key in ("score", "value", "technical_score"):
            if value.get(key) is not None:
                return _num(value.get(key))
        return None
    if value is None:
        return None
    return _num(value)


def _ai_reject_rate(rows: list[dict[str, Any]]) -> float:
    reviewed = []
    for row in rows:
        review = row.get("ai_review") or {}
        action = review.get("review_action") or row.get("ai_decision")
        if action:
            reviewed.append(str(action).upper())
    return _ratio(sum(1 for action in reviewed if action == "REJECT"), len(reviewed))


def _risk_reject_code_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter = Counter()
    for row in rows:
        checks = row.get("risk_failed_checks") or []
        if isinstance(checks, str):
            checks = [checks]
        for check in checks:
            if check:
                counter[str(check)] += 1
        risk = row.get("risk_result") or {}
        code = risk.get("rejection_code") or row.get("risk_rejection_code")
        if code:
            counter[str(code)] += 1
        reason = row.get("risk_reject_reason")
        if reason and not checks and not code:
            counter[str(reason)] += 1
    return dict(counter.most_common())


def _diagnose_zero_trades(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    executed = int(summary.get("executed_trades", 0) or 0)
    if executed > 0:
        return {
            "severity": "info",
            "message": "가상 거래가 발생했습니다. 거래 0건 진단은 필요하지 않습니다.",
            "hints": [],
        }
    total = len(rows)
    if total == 0:
        return {
            "severity": "warning",
            "message": "decision_log가 없습니다. 파이프라인 실행 또는 로그 수집이 먼저 의심됩니다.",
            "hints": [
                "SHADOW_TRADING_ENABLED=true 상태로 analysis worker가 돌았는지 확인하세요.",
                "로그 파일에 'decision_log {json}' 라인이 있는지 확인하세요.",
            ],
        }

    stage_counts = Counter(str(r.get("rejection_stage") or "NONE") for r in rows)
    top_stage, top_stage_count = stage_counts.most_common(1)[0]
    reason_counts = Counter(
        str(r.get("rejection_reason") or "UNKNOWN")
        for r in rows
        if r.get("rejection_reason") or r.get("final_action") == "HOLD"
    )
    top_reason = reason_counts.most_common(1)[0][0] if reason_counts else "UNKNOWN"
    risk_codes = summary.get("risk_reject_code_distribution") or {}
    ai_reject_rate = float(summary.get("ai_reject_rate") or 0.0)

    hints: list[str] = []
    if top_stage in {"decision", "final_decision", "NONE"}:
        message = "거래 0건의 가장 의심되는 원인은 Decision/FinalDecision 단계의 HOLD 조건입니다."
        hints.extend([
            "chart_score 분포와 min_long/min_short threshold를 비교하세요.",
            "shadow 전용 SHADOW_MIN_LONG_SCORE/SHADOW_MIN_SHORT_SCORE 완화가 적용됐는지 확인하세요.",
        ])
    elif top_stage == "ai_review" or ai_reject_rate >= 0.5:
        message = "거래 0건의 가장 의심되는 원인은 AI Reviewer 거절입니다."
        hints.extend([
            "시장 국면별 전략 플레이북에서 candidate.strategy_type이 허용되는지 확인하세요.",
            "shadow에서 샘플 수집 목적이면 SHADOW_AI_REVIEW_REQUIRED=false를 검토하세요.",
        ])
    elif top_stage == "risk" or risk_codes:
        message = "거래 0건의 가장 의심되는 원인은 RiskEngine 거절입니다."
        hints.extend([
            "risk_failed_checks 또는 risk_reject_code 분포를 먼저 보세요.",
            "R:R, 일일 손실 한도, 포지션 수 제한, 잔고 조건을 확인하세요.",
        ])
    elif top_stage == "portfolio":
        message = "거래 0건의 가장 의심되는 원인은 Portfolio 제한입니다."
        hints.append("max concurrent positions 또는 portfolio risk budget을 확인하세요.")
    else:
        message = f"거래 0건의 가장 의심되는 원인은 {top_stage} 단계의 거절입니다."

    return {
        "severity": "warning",
        "message": message,
        "top_rejection_stage": top_stage,
        "top_rejection_stage_rate": _ratio(top_stage_count, total),
        "top_rejection_reason": top_reason,
        "hints": hints,
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
