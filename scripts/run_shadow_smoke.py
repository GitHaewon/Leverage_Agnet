#!/usr/bin/env python
"""Run one safe shadow-mode decision smoke test.

This script never places real orders. It uses deterministic fixture market data,
real deterministic decision/risk/final-decision code, a fake AI reviewer by
default, and the real ShadowExecutionEngine with an in-memory store.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.decision.engine import DecisionEngine, DecisionResult
from agents.decision.final_decision import decide_final_action
from agents.decision.models import AIReviewAction, AIReviewResult, FinalAction
from agents.execution.models import ExecutionRequest
from agents.orchestrator.pipeline import _build_raw_signal_from_candidate, _build_review_input
from agents.risk.engine import RiskEngine
from agents.risk.models import AccountState, UserContext
from agents.shadow.execution import ShadowExecutionEngine
from agents.shadow.models import ShadowTradeRecord

DEFAULT_OUTPUT = Path("logs/shadow_smoke_decisions.jsonl")


@dataclass
class _Macd:
    histogram: float = 125.0
    cross: str = "bullish"


@dataclass
class _Ema:
    alignment: str = "bullish"


@dataclass
class _BollingerBands:
    percent_b: float = 0.22
    bandwidth: float = 4.0


@dataclass
class _TimeframeAnalysis:
    timeframe: str
    close: float = 67000.0
    rsi: float = 34.0
    macd: _Macd = field(default_factory=_Macd)
    ema: _Ema = field(default_factory=_Ema)
    bollinger_bands: _BollingerBands = field(default_factory=_BollingerBands)
    volume_ratio: float = 1.35
    atr: float = 520.0


@dataclass
class _TechnicalFixture:
    tech_score: float = 0.72
    latest_close: float = 67000.0
    support_levels: list[float] | None = None
    resistance_levels: list[float] | None = None
    analyses: dict[str, _TimeframeAnalysis] | None = None

    def __post_init__(self) -> None:
        self.support_levels = self.support_levels or [66600.0, 66000.0, 65000.0]
        self.resistance_levels = self.resistance_levels or [70000.0, 71500.0]
        self.analyses = self.analyses or {
            "1h": _TimeframeAnalysis("1h"),
            "4h": _TimeframeAnalysis("4h", rsi=42.0, volume_ratio=1.1),
        }


@dataclass
class _StrategyFixture:
    direction: str = "LONG"
    confidence: float = 0.84
    entry: Decimal = Decimal("67000")
    take_profit: Decimal = Decimal("70000")
    stop_loss: Decimal = Decimal("66000")
    leverage: int = 5
    margin_ratio: float = 0.015
    funding_rate: float = -0.0002
    oi_1h_change_pct: float = 0.8
    long_short_ratio: float = 0.92
    long_account_pct: float = 47.0
    news_items: list[dict[str, Any]] = field(default_factory=list)
    fear_greed_index: int = 42
    fear_greed_label: str = "Fear"


class _NoopRedis:
    """Minimal async Redis duck type for RiskEngine safety checks."""

    async def exists(self, *_args: Any, **_kwargs: Any) -> int:
        return 0

    async def get(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def set(self, *_args: Any, **_kwargs: Any) -> bool:
        return True

    async def delete(self, *_args: Any, **_kwargs: Any) -> int:
        return 0


class _MemoryShadowStore:
    def __init__(self) -> None:
        self.records: list[ShadowTradeRecord] = []

    async def save(self, record: ShadowTradeRecord) -> None:
        self.records.append(record)


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name: str) -> str:
    value = os.getenv(name)
    return "<unset>" if value is None else value


def _coin_from_symbol(symbol: str) -> str:
    return symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()


def _market_snapshot(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "current_price": 67000.0,
        "price_change_pct": 0.8,
        "recent_price_change_pct": 0.8,
        "volume_ratio": 1.35,
        "volume_change_pct": 18.0,
        "spread_bps": 1.0,
        "funding_rate": -0.0002,
        "open_interest": 28_000_000_000.0,
        "oi_change_pct": 0.8,
        "long_short_ratio": 0.92,
        "long_account_pct": 47.0,
        "short_account_pct": 53.0,
        "news": [],
        "fear_greed": {"index": 42, "label": "Fear"},
    }


def _account() -> AccountState:
    return AccountState(
        available_balance=Decimal("10000"),
        total_balance=Decimal("10000"),
        initial_balance=Decimal("10000"),
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )


def _user_ctx() -> UserContext:
    return UserContext(
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000019"),
        plan="pro",
        risk_profile="moderate",
        risk_per_trade=0.02,
        max_leverage=10,
        max_concurrent_positions=5,
        daily_loss_limit_pct=0.03,
        is_trading_active=True,
        allowed_hours_start=None,
        allowed_hours_end=None,
    )


def _fake_review(decision: DecisionResult) -> AIReviewResult:
    candidate = decision.candidate
    if candidate.action == FinalAction.HOLD:
        return AIReviewResult(
            review_action=AIReviewAction.REJECT,
            confidence=0.90,
            critical_contradiction=False,
            risk_warnings=[],
            reason_summary="fake reviewer: candidate is HOLD",
        )
    return AIReviewResult(
        review_action=AIReviewAction.APPROVE,
        confidence=0.86,
        critical_contradiction=False,
        risk_warnings=[],
        reason_summary="fake reviewer: deterministic fixture approval",
    )


async def _real_review(decision: DecisionResult, symbol: str) -> AIReviewResult:
    from agents.analyst.agent import OpenAIClient
    from agents.synthesis.agent import ReviewerAgent

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("--use-real-ai requires OPENAI_API_KEY")
    reviewer = ReviewerAgent(client=OpenAIClient(api_key=api_key))
    return await reviewer.review(_build_review_input(symbol, decision, decision.candidate))


def _risk_summary(validation: Any) -> dict[str, Any]:
    return {
        "approved": bool(getattr(validation, "approved", False)),
        "rejection_code": getattr(validation, "rejection_code", None),
        "rejection_reason": getattr(validation, "rejection_reason", None),
        "quantity": _json_value(getattr(validation, "quantity", None)),
        "final_leverage": getattr(validation, "final_leverage", None),
        "margin_required_usdt": _json_value(getattr(validation, "margin_required_usdt", None)),
        "max_loss_usdt": _json_value(getattr(validation, "max_loss_usdt", None)),
        "max_profit_usdt": _json_value(getattr(validation, "max_profit_usdt", None)),
        "rr_ratio": _json_value(getattr(validation, "rr_ratio", None)),
        "failed_checks": list(getattr(validation, "failed_checks", []) or []),
        "warnings": list(getattr(validation, "warnings", []) or []),
    }


def _review_summary(review: AIReviewResult) -> dict[str, Any]:
    return {
        "review_action": review.review_action.value,
        "confidence": review.confidence,
        "critical_contradiction": review.critical_contradiction,
        "risk_warnings": review.risk_warnings,
        "reason_summary": review.reason_summary,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _closed_sample_row(
    *,
    timestamp: str,
    symbol: str,
    coin: str,
    action: str,
    strategy_type: str,
    status: str,
    net_pnl: Decimal,
    gross_pnl: Decimal,
    expected_fees: Decimal,
    expected_slippage_cost: Decimal,
    actual_rr: float,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "coin": coin,
        "market_regime": "TREND_UP" if action == "LONG" else "TREND_DOWN",
        "candidate_action": action,
        "final_action": action,
        "strategy_type": strategy_type,
        "expected_gross_profit": str(abs(gross_pnl)) if net_pnl > 0 else "0",
        "expected_gross_loss": str(abs(gross_pnl)) if net_pnl < 0 else "0",
        "expected_net_profit": str(net_pnl) if net_pnl > 0 else "0",
        "expected_net_loss": str(abs(net_pnl)) if net_pnl < 0 else "0",
        "expected_fees": str(expected_fees),
        "expected_slippage_cost": str(expected_slippage_cost),
        "actual_rr": actual_rr,
        "spread_bps": 1.0,
        "funding_rate": -0.0001 if action == "LONG" else 0.0001,
        "ai_review": {
            "review_action": "APPROVE",
            "confidence": 0.86,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": "closed sample fixture",
        },
        "risk_result": {
            "approved": True,
            "rejection_code": None,
            "rejection_reason": None,
            "failed_checks": [],
            "warnings": [],
        },
        "risk_failed_checks": [],
        "rejection_reason": None,
        "actual_result": {
            "executed": True,
            "closed": True,
            "status": status,
            "mode": "paper",
            "net_pnl": str(net_pnl),
            "gross_pnl": str(gross_pnl),
            "holding_minutes": 45,
        },
    }


def _hold_sample_row(timestamp: str, symbol: str, coin: str) -> dict[str, Any]:
    reason = "sample HOLD rejection: insufficient confluence"
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "coin": coin,
        "market_regime": "RANGE",
        "candidate_action": "HOLD",
        "final_action": "HOLD",
        "strategy_type": "INTRADAY",
        "expected_gross_profit": None,
        "expected_gross_loss": None,
        "expected_net_profit": None,
        "expected_net_loss": None,
        "expected_fees": "0",
        "expected_slippage_cost": "0",
        "actual_rr": 0.0,
        "spread_bps": 1.5,
        "funding_rate": 0.0,
        "ai_review": {
            "review_action": "REJECT",
            "confidence": 0.72,
            "critical_contradiction": False,
            "risk_warnings": [],
            "reason_summary": reason,
        },
        "risk_result": {
            "approved": False,
            "rejection_code": "SAMPLE_HOLD",
            "rejection_reason": reason,
            "failed_checks": ["SAMPLE_HOLD"],
            "warnings": [],
        },
        "risk_failed_checks": ["SAMPLE_HOLD"],
        "rejection_reason": reason,
        "actual_result": {
            "executed": False,
            "closed": False,
            "mode": "paper",
        },
    }


def _closed_sample_rows(symbol: str) -> list[dict[str, Any]]:
    coin = _coin_from_symbol(symbol)
    now = datetime.now(timezone.utc).isoformat()
    return [
        _closed_sample_row(
            timestamp=now,
            symbol=symbol,
            coin=coin,
            action="LONG",
            strategy_type="TREND_FOLLOWING",
            status="TP_HIT",
            net_pnl=Decimal("100"),
            gross_pnl=Decimal("120"),
            expected_fees=Decimal("12"),
            expected_slippage_cost=Decimal("8"),
            actual_rr=2.4,
        ),
        _closed_sample_row(
            timestamp=now,
            symbol=symbol,
            coin=coin,
            action="LONG",
            strategy_type="TREND_FOLLOWING",
            status="SL_HIT",
            net_pnl=Decimal("-50"),
            gross_pnl=Decimal("-45"),
            expected_fees=Decimal("3"),
            expected_slippage_cost=Decimal("2"),
            actual_rr=2.1,
        ),
        _closed_sample_row(
            timestamp=now,
            symbol=symbol,
            coin=coin,
            action="SHORT",
            strategy_type="BREAKOUT",
            status="TP_HIT",
            net_pnl=Decimal("80"),
            gross_pnl=Decimal("95"),
            expected_fees=Decimal("10"),
            expected_slippage_cost=Decimal("5"),
            actual_rr=2.8,
        ),
        _hold_sample_row(now, symbol, coin),
    ]


def write_closed_sample_rows(symbol: str, output: Path) -> list[dict[str, Any]]:
    rows = _closed_sample_rows(symbol.upper())
    for row in rows:
        _write_jsonl(output, row)
    return rows


async def run_smoke(
    symbol: str,
    output: Path,
    use_real_ai: bool = False,
    include_closed_samples: bool = False,
) -> dict[str, Any]:
    if _env_bool("LIVE_TRADING_ENABLED"):
        raise RuntimeError("Refusing to run: LIVE_TRADING_ENABLED=true")
    if include_closed_samples and use_real_ai:
        raise RuntimeError("--include-closed-samples cannot be combined with --use-real-ai")

    symbol = symbol.upper()
    coin = _coin_from_symbol(symbol)
    account = _account()
    ctx = _user_ctx()

    decision = DecisionEngine().run(
        coin=coin,
        symbol=symbol,
        market_snapshot=_market_snapshot(symbol),
        technical_result=_TechnicalFixture(),
        strategy_signal=_StrategyFixture(),
        account_state=account,
        config={
            "min_long_score": 60.0,
            "default_margin_ratio": 0.015,
            "slippage_bps": 2.0,
        },
    )
    candidate = decision.candidate

    ai_review = await _real_review(decision, symbol) if use_real_ai else _fake_review(decision)

    risk_engine = RiskEngine(_NoopRedis())  # type: ignore[arg-type]
    validation = await risk_engine.validate_candidate(
        candidate=candidate,
        ctx=ctx,
        account=account,
        daily_loss_usdt=Decimal("0"),
        weekly_loss_usdt=Decimal("0"),
        weekly_limit_usdt=Decimal("800"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
        market_regime=decision.regime,
        funding_context={"is_funding_window": False, "minutes_to_funding": 120},
        config={"min_expected_net_profit_pct": 0.001},
    )

    final_decision = decide_final_action(candidate, ai_review, validation)
    execution_result = None
    shadow_store = _MemoryShadowStore()
    if final_decision.action in (FinalAction.LONG, FinalAction.SHORT) and validation.approved:
        raw_signal = _build_raw_signal_from_candidate(
            coin, symbol, candidate, decision.confidence
        )
        execution_result = await ShadowExecutionEngine(
            risk_validator=risk_engine,
            store=shadow_store,
        ).execute(
            ExecutionRequest(
                signal=raw_signal,
                user_ctx=ctx,
                account=account,
                daily_loss_usdt=Decimal("0"),
                weekly_loss_usdt=Decimal("0"),
                weekly_limit_usdt=Decimal("800"),
                consecutive_losses=0,
                open_positions_count=0,
                same_coin_position=None,
                candidate=candidate,
                final_decision=final_decision,
                approved_validation=validation,
            )
        )

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "coin": coin,
        "market_regime": getattr(getattr(decision.regime, "regime", None), "value", "UNKNOWN"),
        "candidate_action": candidate.action.value,
        "final_action": final_decision.action.value,
        "strategy_type": candidate.strategy_type.value,
        "expected_gross_profit": _json_value(candidate.expected_gross_profit),
        "expected_gross_loss": _json_value(candidate.expected_gross_loss),
        "expected_net_profit": _json_value(candidate.expected_net_profit),
        "expected_net_loss": _json_value(candidate.expected_net_loss),
        "expected_fees": _json_value(candidate.expected_fees),
        "expected_slippage_cost": _json_value(candidate.expected_slippage_cost),
        "actual_rr": candidate.actual_rr,
        "ai_review": _review_summary(ai_review),
        "risk_result": _risk_summary(validation),
        "risk_failed_checks": list(getattr(validation, "failed_checks", []) or []),
        "rejection_reason": (
            getattr(validation, "rejection_reason", None)
            if final_decision.action == FinalAction.HOLD
            else None
        ) or (final_decision.reason if final_decision.action == FinalAction.HOLD else None),
        "decision_reasons": list(getattr(candidate, "reasons", []) or []),
        "actual_result": {
            "executed": bool(getattr(execution_result, "executed", False)),
            "approved": bool(getattr(execution_result, "approved", False)),
            "mode": getattr(execution_result, "mode", "paper"),
            "shadow_records_saved": len(shadow_store.records),
            "rejection_code": getattr(execution_result, "rejection_code", None),
            "rejection_reason": getattr(execution_result, "rejection_reason", None),
        },
    }
    _write_jsonl(output, payload)
    if include_closed_samples:
        payload["closed_samples_written"] = len(write_closed_sample_rows(symbol, output))
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one local shadow smoke decision")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol to evaluate")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSONL output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--use-real-ai",
        action="store_true",
        help="Call the real AI reviewer. Default uses a fake reviewer fixture.",
    )
    parser.add_argument(
        "--include-closed-samples",
        action="store_true",
        help="Append deterministic closed sample rows for analyzer metric checks.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("Safety settings:")
    print(f"  LIVE_TRADING_ENABLED={_env_text('LIVE_TRADING_ENABLED')}")
    print(f"  SHADOW_TRADING_ENABLED={_env_text('SHADOW_TRADING_ENABLED')}")
    print(f"  BINANCE_TESTNET={_env_text('BINANCE_TESTNET')}")
    print(f"  USE_TESTNET={_env_text('USE_TESTNET')}")
    print(f"  use_real_ai={args.use_real_ai}")

    try:
        payload = asyncio.run(
            run_smoke(
                args.symbol,
                args.output,
                args.use_real_ai,
                args.include_closed_samples,
            )
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Final action: {payload['final_action']}")
    print(f"Strategy: {payload['strategy_type']}")
    print(f"Executed in shadow: {payload['actual_result']['executed']}")
    if args.include_closed_samples:
        print(f"Closed sample rows written: {payload.get('closed_samples_written', 0)}")
    print(f"Wrote shadow smoke decision log: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
