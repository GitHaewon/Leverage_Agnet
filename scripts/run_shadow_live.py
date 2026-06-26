#!/usr/bin/env python
"""Live shadow trading runner.

Fetches real Binance Futures market data and runs the full decision pipeline
in shadow (paper) mode — no real orders are placed.

Steps:
  1. BinanceRestClient  → live OHLCV, funding rate, open interest
  2. TechnicalAnalysisAgent
  3. StrategyEngine
  4. DecisionEngine
  5. AI Reviewer (fake by default, --use-real-ai for OpenAI)
  6. RiskEngine
  7. ShadowExecutionEngine (in-memory, no DB)
  8. Append result to logs/shadow_live_decisions.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.decision.constants import MAX_RISK_SCORE, MIN_LONG_SCORE, MIN_SHORT_SCORE
from agents.decision.engine import DecisionEngine
from agents.decision.final_decision import decide_final_action
from agents.decision.models import AIReviewAction, AIReviewResult, FinalAction
from agents.execution.models import ExecutionRequest
from agents.market_data.rest_client import BinanceRestClient
from agents.orchestrator.pipeline import (
    _build_raw_signal_from_candidate,
    _build_review_input,
    _decision_score_diagnostics,
)
from agents.risk.engine import RiskEngine
from agents.risk.models import AccountState, UserContext
from agents.shadow.execution import ShadowExecutionEngine
from agents.shadow.models import ShadowTradeRecord
from agents.strategy.engine import StrategyEngine
from agents.strategy.models import StrategyInput
from agents.technical_analysis.agent import TechnicalAnalysisAgent

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("logs/shadow_live_decisions.jsonl")
_KLINE_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")
_KLINE_LIMIT = 200
_ENV_FILES = (ROOT / ".env", ROOT / "backend" / ".env")


class _NoopRedis:
    async def exists(self, *_a: Any, **_k: Any) -> int:
        return 0

    async def get(self, *_a: Any, **_k: Any) -> None:
        return None

    async def set(self, *_a: Any, **_k: Any) -> bool:
        return True

    async def delete(self, *_a: Any, **_k: Any) -> int:
        return 0


class _MemoryShadowStore:
    def __init__(self) -> None:
        self.records: list[ShadowTradeRecord] = []

    async def save(self, record: ShadowTradeRecord) -> None:
        self.records.append(record)


def _klines_to_df(klines: list) -> pd.DataFrame:
    rows = [
        {
            "open":   float(k.open),
            "high":   float(k.high),
            "low":    float(k.low),
            "close":  float(k.close),
            "volume": float(k.volume),
        }
        for k in klines
    ]
    return pd.DataFrame(rows)


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


def _fake_review(decision: Any) -> AIReviewResult:
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
        reason_summary="fake reviewer: live shadow approval",
    )


async def _real_review(decision: Any, symbol: str) -> AIReviewResult:
    from agents.analyst.agent import OpenAIClient
    from agents.synthesis.agent import ReviewerAgent

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("--use-real-ai requires OPENAI_API_KEY env var")
    reviewer = ReviewerAgent(client=OpenAIClient(api_key=api_key))
    return await reviewer.review(_build_review_input(symbol, decision, decision.candidate))


def _risk_summary(validation: Any) -> dict[str, Any]:
    return {
        "approved": bool(getattr(validation, "approved", False)),
        "rejection_code": getattr(validation, "rejection_code", None),
        "rejection_reason": getattr(validation, "rejection_reason", None),
        "quantity": _json_val(getattr(validation, "quantity", None)),
        "final_leverage": getattr(validation, "final_leverage", None),
        "margin_required_usdt": _json_val(getattr(validation, "margin_required_usdt", None)),
        "max_loss_usdt": _json_val(getattr(validation, "max_loss_usdt", None)),
        "max_profit_usdt": _json_val(getattr(validation, "max_profit_usdt", None)),
        "rr_ratio": _json_val(getattr(validation, "rr_ratio", None)),
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


def _json_val(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "value"):
        return v.value
    return v


def _write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


async def _fetch_live_data(symbol: str, testnet: bool) -> dict[str, Any]:
    """Binance REST에서 OHLCV, funding, OI, 현재가를 일괄 조회한다."""
    async with BinanceRestClient(testnet=testnet) as client:
        since = datetime.now(timezone.utc) - timedelta(hours=_KLINE_LIMIT * 4 + 1)
        ohlcv: dict[str, pd.DataFrame] = {}
        for interval in _KLINE_INTERVALS:
            klines = await client.get_klines(symbol, interval, since=since, limit=_KLINE_LIMIT)
            if len(klines) >= 30:
                ohlcv[interval] = _klines_to_df(klines)
            else:
                logger.warning("Not enough klines for %s/%s: %d", symbol, interval, len(klines))

        funding, oi = await client.get_funding_and_oi(symbol)

    current_price: float = 0.0
    if "1m" in ohlcv and len(ohlcv["1m"]) > 0:
        current_price = float(ohlcv["1m"].iloc[-1]["close"])
    elif "5m" in ohlcv and len(ohlcv["5m"]) > 0:
        current_price = float(ohlcv["5m"].iloc[-1]["close"])

    funding_rate = float(getattr(funding, "funding_rate", 0.0) or 0.0) if funding else 0.0
    open_interest = float(getattr(oi, "open_interest", 0.0) or 0.0) if oi else 0.0

    market_snapshot: dict[str, Any] = {
        "symbol": symbol,
        "coin": symbol[:-4] if symbol.upper().endswith("USDT") else symbol,
        "current_price": current_price,
        "price": current_price,
        "price_change_pct": 0.0,
        "volume_ratio": 1.0,
        "volume_change_pct": 0.0,
        "spread_bps": 1.0,
        "funding_rate": funding_rate,
        "open_interest": open_interest,
        "oi_change_pct": 0.0,
        "long_short_ratio": None,
        "long_account_pct": None,
        "short_account_pct": None,
        "news": [],
        "fear_greed": None,
        "ohlcv": ohlcv,
    }
    return market_snapshot


async def run_live(
    symbol: str,
    output: Path,
    use_real_ai: bool = False,
    testnet: bool = False,
    decision_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Refusing: LIVE_TRADING_ENABLED=true — shadow runner must not run with live trading on")

    symbol = symbol.upper()
    coin = symbol[:-4] if symbol.upper().endswith("USDT") else symbol.upper()
    account = _account()
    ctx = _user_ctx()

    print(f"[1/7] Fetching live market data for {symbol} …")
    snap = await _fetch_live_data(symbol, testnet=testnet)
    current_price = snap["current_price"]
    print(f"      current_price={current_price:.2f}  funding={snap['funding_rate']:.6f}  OI={snap['open_interest']:.0f}")

    ohlcv: dict[str, pd.DataFrame] = snap.get("ohlcv", {})
    if not ohlcv:
        raise RuntimeError(f"No OHLCV data fetched for {symbol}")

    print("[2/7] Running TechnicalAnalysisAgent …")
    ta_agent = TechnicalAnalysisAgent()
    tech_result = ta_agent.run(ohlcv, coin=coin, symbol=symbol)
    print(f"      tech_score={tech_result.tech_score:.3f}")

    print("[3/7] Running StrategyEngine …")
    strategy_inp = StrategyInput(
        coin=coin,
        symbol=symbol,
        current_price=Decimal(str(current_price)),
        ta_result=tech_result,
    )
    strategy_engine = StrategyEngine()
    strategy_signal = strategy_engine.evaluate(strategy_inp)
    print(f"      direction={strategy_signal.direction}  confidence={strategy_signal.confidence:.3f}")

    print("[4/7] Running DecisionEngine …")
    decision_config = decision_config or build_shadow_decision_config()
    decision = DecisionEngine().run(
        coin=coin,
        symbol=symbol,
        market_snapshot=snap,
        technical_result=tech_result,
        strategy_signal=strategy_signal,
        account_state=account,
        config=decision_config,
    )
    candidate = decision.candidate
    print(f"      candidate={candidate.action.value}  reasons={len(getattr(candidate, 'reasons', []))}")

    print("[5/7] Running AI Reviewer …")
    ai_review = await _real_review(decision, symbol) if use_real_ai else _fake_review(decision)
    print(f"      review={ai_review.review_action.value}  confidence={ai_review.confidence:.2f}")

    print("[6/7] Running RiskEngine …")
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
    print(f"      risk_approved={validation.approved}  checks={getattr(validation, 'failed_checks', [])}")

    final_decision = decide_final_action(candidate, ai_review, validation)

    print("[7/7] Running ShadowExecutionEngine …")
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

    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "coin": coin,
        "current_price": current_price,
        "funding_rate": snap["funding_rate"],
        "market_regime": getattr(getattr(decision.regime, "regime", None), "value", "UNKNOWN"),
        **_decision_score_diagnostics(decision, decision_config),
        "candidate_action": candidate.action.value,
        "final_action": final_decision.action.value,
        "strategy_type": candidate.strategy_type.value,
        "tech_score": tech_result.tech_score,
        "strategy_direction": strategy_signal.direction,
        "strategy_confidence": strategy_signal.confidence,
        "expected_gross_profit": _json_val(candidate.expected_gross_profit),
        "expected_gross_loss": _json_val(candidate.expected_gross_loss),
        "expected_net_profit": _json_val(candidate.expected_net_profit),
        "expected_net_loss": _json_val(candidate.expected_net_loss),
        "expected_fees": _json_val(candidate.expected_fees),
        "expected_slippage_cost": _json_val(candidate.expected_slippage_cost),
        "actual_rr": candidate.actual_rr,
        "ai_review": _review_summary(ai_review),
        "risk_result": _risk_summary(validation),
        "risk_failed_checks": list(getattr(validation, "failed_checks", []) or []),
        "rejection_reason": (
            getattr(validation, "rejection_reason", None)
            if final_decision.action == FinalAction.HOLD else None
        ) or (final_decision.reason if final_decision.action == FinalAction.HOLD else None),
        "decision_reasons": list(getattr(candidate, "reasons", []) or []),
        "actual_result": {
            "executed": bool(getattr(execution_result, "executed", False)),
            "approved": bool(getattr(execution_result, "approved", False)),
            "mode": getattr(execution_result, "mode", "paper"),
            "shadow_records_saved": len(shadow_store.records),
            "rejection_code": getattr(execution_result, "rejection_code", None),
        },
    }
    _write_jsonl(output, payload)
    return payload


def build_shadow_decision_config(
    *,
    min_long_score: float | None = None,
    min_short_score: float | None = None,
    max_risk_score: float | None = None,
) -> dict[str, Any]:
    """Build the shadow-only DecisionEngine config for this standalone runner."""
    _load_env_files()
    min_long = _float_setting("SHADOW_MIN_LONG_SCORE", min_long_score, MIN_LONG_SCORE)
    min_short = _float_setting("SHADOW_MIN_SHORT_SCORE", min_short_score, MIN_SHORT_SCORE)
    max_risk = _float_setting("SHADOW_MAX_RISK_SCORE", max_risk_score, MAX_RISK_SCORE)
    return {
        "profile": "shadow",
        "min_long_score": min_long,
        "min_short_score": min_short,
        "max_risk_score": max_risk,
        "max_risk_trend": max_risk,
        "max_risk_breakout": max_risk,
        "max_risk_intraday": max_risk,
        "max_risk_scalping": max_risk,
        "default_margin_ratio": 0.015,
        "slippage_bps": 2.0,
    }


def _float_setting(env_key: str, override: float | None, default: float) -> float:
    if override is not None:
        return float(override)
    raw = os.environ.get(env_key)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_key} must be a number, got {raw!r}") from exc


def _load_env_files() -> None:
    for path in _ENV_FILES:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live shadow trading runner (no real orders)")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol (default: BTCUSDT)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--use-real-ai", action="store_true",
                        help="Use real OpenAI reviewer (requires OPENAI_API_KEY)")
    parser.add_argument("--testnet", action="store_true",
                        help="Use Binance Testnet REST endpoints")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously instead of a single decision cycle")
    parser.add_argument("--interval-seconds", type=int, default=300,
                        help="Seconds between loop cycles (default: 300)")
    parser.add_argument("--max-cycles", type=int, default=0,
                        help="Stop after N cycles; 0 means run until interrupted")
    parser.add_argument("--shadow-min-long-score", type=float, default=None,
                        help="Override SHADOW_MIN_LONG_SCORE for this run")
    parser.add_argument("--shadow-min-short-score", type=float, default=None,
                        help="Override SHADOW_MIN_SHORT_SCORE for this run")
    parser.add_argument("--shadow-max-risk-score", type=float, default=None,
                        help="Override SHADOW_MAX_RISK_SCORE for this run")
    return parser.parse_args(argv)


def _print_summary(payload: dict[str, Any], output: Path) -> None:
    print()
    print("=" * 60)
    print(f"  Final action : {payload['final_action']}")
    print(f"  Strategy     : {payload['strategy_type']}")
    print(f"  Market regime: {payload['market_regime']}")
    print(f"  Price        : {payload['current_price']:.2f} USDT")
    print(f"  Tech score   : {payload['tech_score']:.3f}")
    print(
        "  Thresholds   : "
        f"long>={payload['min_long_score']:.2f}, "
        f"short>={payload['min_short_score']:.2f}, "
        f"risk<={payload['max_risk_score']:.2f}"
    )
    print(
        "  Scores       : "
        f"long={payload['long_score']:.2f}, "
        f"short={payload['short_score']:.2f}, "
        f"risk={payload['risk_score']:.2f}"
    )
    print(f"  Executed     : {payload['actual_result']['executed']}")
    if payload.get("rejection_reason"):
        print(f"  Rejected     : {payload['rejection_reason']}")
    print(f"\n  Log -> {output}")


def _main_loop(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval_seconds <= 0:
        print("ERROR: --interval-seconds must be greater than 0", file=sys.stderr)
        return 2
    if args.max_cycles < 0:
        print("ERROR: --max-cycles must be 0 or greater", file=sys.stderr)
        return 2

    print("=" * 60)
    print(f"  Shadow Trading Live Runner  |  {args.symbol}")
    print(f"  testnet={args.testnet}  use_real_ai={args.use_real_ai}")
    if args.loop:
        max_cycles = args.max_cycles or "unlimited"
        print(f"  loop=True  interval_seconds={args.interval_seconds}  max_cycles={max_cycles}")
    decision_config = build_shadow_decision_config(
        min_long_score=args.shadow_min_long_score,
        min_short_score=args.shadow_min_short_score,
        max_risk_score=args.shadow_max_risk_score,
    )
    print(
        "  shadow_thresholds="
        f"long>={decision_config['min_long_score']:.2f}, "
        f"short>={decision_config['min_short_score']:.2f}, "
        f"risk<={decision_config['max_risk_score']:.2f}"
    )
    print("=" * 60)

    cycles = 0
    while True:
        cycle_started = time.monotonic()
        cycles += 1
        if args.loop:
            print(f"\n--- Shadow cycle {cycles} started at {datetime.now(timezone.utc).isoformat()} ---")

        try:
            payload = asyncio.run(
                run_live(
                    args.symbol,
                    args.output,
                    args.use_real_ai,
                    args.testnet,
                    decision_config,
                )
            )
        except KeyboardInterrupt:
            print("\nInterrupted; stopping shadow loop.")
            return 130
        except RuntimeError as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            if not args.loop:
                return 2
        except Exception as exc:
            print(f"\nUNEXPECTED ERROR: {exc}", file=sys.stderr)
            logger.exception("run_live failed")
            if not args.loop:
                return 1
        else:
            _print_summary(payload, args.output)

        if not args.loop:
            return 0
        if args.max_cycles and cycles >= args.max_cycles:
            print(f"\nReached max cycles ({args.max_cycles}); stopping.")
            return 0

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(0.0, args.interval_seconds - elapsed)
        print(f"\nNext shadow cycle in {sleep_for:.1f}s.")
        time.sleep(sleep_for)


def main(argv: list[str] | None = None) -> int:
    return _main_loop(argv)


if __name__ == "__main__":
    raise SystemExit(main())
