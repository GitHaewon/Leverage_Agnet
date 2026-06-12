"""
Agent Orchestrator Pipeline — 결정적 의사결정 플로우.

각 단계 실패가 전체를 멈추지 않도록 격리하며, 안전 원칙상 불확실성은 항상
HOLD/REJECT로 귀결시킨다.

실행 순서:
  1. MarketDataAgent      CRITICAL  실패 → FAILED
  2. TechnicalAnalysis    DEGRADED  실패 → 중립값(tech_score=0.0)으로 계속
  3. StrategyEngine       DEGRADED  실패 → 중립값으로 계속
  4. DecisionEngine       결정적     국면/점수/전략선택/후보 생성. 예외 → HOLD
                                     candidate.action=HOLD → HOLD
  5. AI Reviewer          검토 전용   APPROVE/REJECT만. 파싱 실패/예외 → 안전 REJECT → HOLD
  6. RiskEngine           GATE       validate_candidate. 예외/거부 → HOLD (실행 없음)
  7. FinalDecision        결정적     candidate+review+risk 조립. HOLD → 실행 없음
  8. PortfolioManager     GATE       실패/거부 → REJECTED
  9. PositionManager      실패 → FAILED
 10. ExecutionEngine      실패 → FAILED (retry=3), TP/SL 실패 → 긴급 청산

안전 원칙 (CLAUDE.md):
  - AI는 방향/진입가/TP/SL/레버리지/사이즈를 만들거나 바꿀 수 없다 — 검토만.
  - RiskEngine이 Portfolio/PositionManager/Execution 직전의 최종 안전 게이트다.
  - FinalDecision이 LONG/SHORT일 때만 실행 경로에 도달한다. HOLD는 실행 금지.
  - 분류/점수/후보생성/AI리뷰/리스크/최종결정 중 어떤 예외도 HOLD/REJECT로 귀결.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

from agents.orchestrator.logger import OrchestratorLogger
from agents.orchestrator.models import (
    AgentResult,
    PipelineContext,
    PipelineInput,
    PipelineResult,
    PipelineStatus,
    PostTradeEvent,
)
from agents.orchestrator.runner import AgentRunner

logger = logging.getLogger(__name__)


# ── 에이전트 프로토콜 (의존성 주입 인터페이스) ────────────────────────────────────

@runtime_checkable
class MarketDataProvider(Protocol):
    """MarketDataAgent 스냅샷 조회 인터페이스."""
    async def get_snapshot(self, coin: str) -> dict: ...


@runtime_checkable
class TechnicalAnalystProvider(Protocol):
    """TechnicalAnalysisAgent 인터페이스."""
    def run(
        self,
        ohlcv_data: dict,
        coin: str,
        symbol: str | None = None,
    ) -> Any: ...


@runtime_checkable
class StrategyProvider(Protocol):
    """StrategyEngine 인터페이스."""
    def evaluate(self, inp: Any) -> Any: ...


@runtime_checkable
class DecisionProvider(Protocol):
    """결정적 의사결정 체인 (DecisionEngine) 인터페이스."""
    def run(
        self,
        *,
        coin: str,
        symbol: str,
        market_snapshot: Any,
        technical_result: Any,
        strategy_signal: Any,
        account_state: Any,
        config: Any = None,
    ) -> Any: ...


@runtime_checkable
class ReviewerProvider(Protocol):
    """AI 리뷰어 (ReviewerAgent) 인터페이스 — TradeCandidate 검토 전용."""
    async def review(self, review_input: Any) -> Any: ...


@runtime_checkable
class RiskProvider(Protocol):
    """RiskEngine 인터페이스 — 결정적 TradeCandidate 검증."""
    async def validate_candidate(
        self,
        candidate: Any,
        ctx: Any,
        account: Any,
        daily_loss_usdt: Any,
        weekly_loss_usdt: Any,
        weekly_limit_usdt: Any,
        consecutive_losses: int,
        open_positions_count: int,
        same_coin_position: Any,
        market_regime: Any = None,
        funding_context: Any = None,
        config: Any = None,
    ) -> Any: ...


@runtime_checkable
class PortfolioProvider(Protocol):
    """PortfolioEngine 인터페이스."""
    def can_add_position(
        self,
        positions: Any,
        account: Any,
        new_risk_usdt: Any,
    ) -> tuple[bool, str]: ...


@runtime_checkable
class PositionManagerProvider(Protocol):
    """PositionManagerEngine 인터페이스."""
    def open(
        self,
        user_id: str,
        signal: Any,
        validation: Any,
    ) -> Any: ...


@runtime_checkable
class ExecutionProvider(Protocol):
    """ExecutionEngine 인터페이스."""
    async def execute(self, req: Any) -> Any: ...


@runtime_checkable
class PostTradeHookProvider(Protocol):
    """실거래 체결 후 SafetyGate 손실 누적 인터페이스."""
    async def on_trade_executed(self, event: PostTradeEvent) -> None: ...


@runtime_checkable
class AlertDispatcherProvider(Protocol):
    """긴급 청산 등 중요 이벤트를 Telegram으로 발송하는 인터페이스."""
    async def dispatch(self, event: Any) -> Any: ...


# ── 스텝 설정 ──────────────────────────────────────────────────────────────────

_STEP_NAMES: list[str] = [
    "market_data",
    "technical",
    "strategy",
    "decision",
    "ai_review",
    "risk",
    "final_decision",
    "portfolio",
    "position_manager",
    "execution",
]

_STEP_TIMEOUT: dict[str, float] = {
    "market_data":       10.0,
    "technical":         10.0,
    "strategy":           5.0,
    "decision":           5.0,
    "ai_review":         30.0,   # OpenAI API 포함
    "risk":               5.0,
    "final_decision":     3.0,
    "portfolio":          3.0,
    "position_manager":   3.0,
    "execution":         15.0,
}

_STEP_RETRIES: dict[str, int] = {
    "market_data":        2,
    "technical":          1,
    "strategy":           1,
    "decision":           0,    # 결정적 — 재시도 무의미
    "ai_review":          1,
    "risk":               0,    # 실패 시 즉시 보수적 HOLD
    "final_decision":     0,
    "portfolio":          0,
    "position_manager":   0,
    "execution":          3,    # 주문 실행은 재시도 중요
}


# ── OrchestratorDeps ──────────────────────────────────────────────────────────

@dataclass
class OrchestratorDeps:
    """파이프라인이 의존하는 에이전트 인스턴스 묶음."""
    market_data:      MarketDataProvider
    technical:        TechnicalAnalystProvider
    strategy:         StrategyProvider
    decision:         DecisionProvider
    reviewer:         ReviewerProvider
    risk:             RiskProvider
    portfolio:        PortfolioProvider
    position_manager: PositionManagerProvider
    execution:        ExecutionProvider
    post_trade_hook:  Optional[PostTradeHookProvider]  = None
    alert_dispatcher: Optional[AlertDispatcherProvider] = None


# ── OrchestratorPipeline ──────────────────────────────────────────────────────

class OrchestratorPipeline:
    """
    결정적 의사결정 플로우 파이프라인.

    사용 예:
        deps     = OrchestratorDeps(market_data=..., decision=..., reviewer=..., ...)
        pipeline = OrchestratorPipeline(deps)
        result   = await pipeline.run(PipelineInput(coin="BTC", user_id="...", ...))
    """

    def __init__(
        self,
        deps: OrchestratorDeps,
        runner: AgentRunner | None = None,
        orch_logger: OrchestratorLogger | None = None,
    ) -> None:
        self._deps = deps
        self._runner = runner or AgentRunner()
        self._logger = orch_logger or OrchestratorLogger()

    # ── 진입점 ────────────────────────────────────────────────────────────────

    async def run(self, inp: PipelineInput) -> PipelineResult:
        ctx = PipelineContext(coin=inp.coin, user_id=inp.user_id)
        steps: list[AgentResult] = []
        started = datetime.now(timezone.utc)
        symbol = f"{inp.coin}USDT"

        async def _run_step(
            name: str,
            coro_fn: Callable[[], Awaitable[Any]],
        ) -> AgentResult:
            r = await self._runner.run(
                name,
                coro_fn,
                timeout=_STEP_TIMEOUT.get(name),
                max_retries=_STEP_RETRIES.get(name),
            )
            steps.append(r)
            await self._logger.log_step(ctx.run_id, r)
            return r

        def _finish(
            status: PipelineStatus,
            *,
            rejection_reason: str | None = None,
            skip: list[str] | None = None,
            execution_result: Any = None,
        ) -> PipelineResult:
            if skip:
                _append_skipped(steps, skip, reason=rejection_reason or "upstream")
            finished = datetime.now(timezone.utc)
            result = PipelineResult(
                run_id=ctx.run_id,
                coin=ctx.coin,
                status=status,
                steps=steps,
                execution_result=execution_result,
                rejection_reason=rejection_reason,
                total_latency_ms=(finished - started).total_seconds() * 1000,
                triggered_at=ctx.triggered_at,
                finished_at=finished,
            )
            asyncio.ensure_future(self._logger.log_pipeline(result))
            return result

        # ── Step 1: Market Data ──────────────────────────────────────────────
        r1 = await _run_step(
            "market_data",
            lambda: self._deps.market_data.get_snapshot(inp.coin),
        )
        if r1.failed:
            ctx.errors.append({"agent": "market_data", "error": r1.error})
            return _finish(
                PipelineStatus.FAILED,
                rejection_reason="MarketData 수집 실패",
                skip=_STEP_NAMES[1:],
            )
        ctx.market_snapshot = r1.output
        snap: dict = ctx.market_snapshot

        # ── Step 2: Technical Analysis ────────────────────────────────────────
        ohlcv = snap.get("ohlcv", {}) if isinstance(snap, dict) else {}
        r2 = await _run_step(
            "technical",
            lambda: asyncio.to_thread(
                self._deps.technical.run,
                ohlcv,
                inp.coin,
                symbol,
            ),
        )
        if r2.failed:
            ctx.errors.append({"agent": "technical", "error": r2.error})
            ctx.tech_result = _neutral_ta_result()
            logger.warning("[pipeline] technical 실패 — 중립값 사용")
        else:
            ctx.tech_result = r2.output

        # ── Step 3: Strategy Engine ───────────────────────────────────────────
        from agents.strategy.models import StrategyInput
        current_price = snap.get("current_price", "0") if isinstance(snap, dict) else "0"
        strategy_inp = StrategyInput(
            coin=inp.coin,
            symbol=symbol,
            current_price=Decimal(str(current_price)),
            ta_result=ctx.tech_result,
        )
        r3 = await _run_step(
            "strategy",
            lambda: asyncio.to_thread(self._deps.strategy.evaluate, strategy_inp),
        )
        if r3.failed:
            ctx.errors.append({"agent": "strategy", "error": r3.error})
            ctx.strategy_signal = _neutral_strategy_signal()
            logger.warning("[pipeline] strategy 실패 — 중립값 사용")
        else:
            ctx.strategy_signal = r3.output

        # ── Step 4: Decision Engine (결정적 후보 생성) ─────────────────────────
        r4 = await _run_step(
            "decision",
            lambda: asyncio.to_thread(
                self._deps.decision.run,
                coin=inp.coin,
                symbol=symbol,
                market_snapshot=snap,
                technical_result=ctx.tech_result,
                strategy_signal=ctx.strategy_signal,
                account_state=inp.account_state,
                config=getattr(inp, "decision_config", None),
            ),
        )
        if r4.failed:
            # 분류/점수/후보생성 예외 → 안전하게 HOLD
            ctx.errors.append({"agent": "decision", "error": r4.error})
            logger.warning("[pipeline] decision 실패 — HOLD: %s", r4.error)
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason="결정 단계 오류 — HOLD",
                skip=_STEP_NAMES[4:],
            )
        ctx.decision_result = r4.output
        candidate = getattr(ctx.decision_result, "candidate", None)
        ctx.candidate = candidate

        from agents.decision.models import FinalAction
        if candidate is None or candidate.action == FinalAction.HOLD:
            reason = _candidate_hold_reason(candidate)
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason=reason,
                skip=_STEP_NAMES[4:],
            )

        # ── Step 5: AI Reviewer (검토 전용) ───────────────────────────────────
        review_input = _build_review_input(symbol, ctx.decision_result, candidate)
        r5 = await _run_step(
            "ai_review",
            lambda: self._deps.reviewer.review(review_input),
        )
        from agents.decision.models import AIReviewAction
        if r5.failed:
            # API 오류 등 — 안전 REJECT로 처리하고 HOLD
            ctx.errors.append({"agent": "ai_review", "error": r5.error})
            ctx.ai_review = _safe_reject_review(r5.error or "ai_review_failed")
            logger.warning("[pipeline] ai_review 실패 — 안전 REJECT/HOLD: %s", r5.error)
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason="AI 리뷰 실패 — 안전 REJECT",
                skip=_STEP_NAMES[5:],
            )
        ctx.ai_review = r5.output
        if _review_action(ctx.ai_review) == AIReviewAction.REJECT:
            reason = getattr(ctx.ai_review, "reason_summary", "") or "AI reviewer rejected candidate"
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason=reason,
                skip=_STEP_NAMES[5:],
            )

        # ── RawSignal 생성 (legacy PositionManager / Execution 입력) ──────────
        raw_signal = _build_raw_signal_from_candidate(
            inp.coin, symbol, candidate, getattr(ctx.decision_result, "confidence", 0.0)
        )
        ctx.raw_signal = raw_signal

        # ── Step 6: Risk Engine (최종 안전 게이트) ────────────────────────────
        same_coin = _find_same_coin_position(inp.open_positions, inp.coin)
        regime_result = getattr(ctx.decision_result, "regime", None)
        r6 = await _run_step(
            "risk",
            lambda: self._deps.risk.validate_candidate(
                candidate,
                inp.user_ctx,
                inp.account_state,
                inp.daily_loss_usdt or Decimal("0"),
                inp.weekly_loss_usdt or Decimal("0"),
                inp.weekly_limit_usdt or Decimal("0"),
                inp.consecutive_losses,
                len(inp.open_positions),
                same_coin,
                market_regime=regime_result,
                funding_context=snap.get("funding_context") if isinstance(snap, dict) else None,
            ),
        )
        if r6.failed:
            # RiskEngine 예외 → 보수적으로 HOLD (실행 없음)
            ctx.errors.append({"agent": "risk", "error": r6.error})
            logger.warning("[pipeline] risk 예외 — HOLD: %s", r6.error)
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason="RiskEngine 예외 — 보수적 HOLD",
                skip=_STEP_NAMES[6:],
            )
        ctx.risk_result = r6.output
        if not getattr(ctx.risk_result, "approved", False):
            failed_checks = getattr(ctx.risk_result, "failed_checks", []) or []
            reason = getattr(ctx.risk_result, "rejection_reason", None) or "RiskEngine 거부"
            logger.info(
                "[pipeline] risk 거부 user=%s coin=%s failed_checks=%s reason=%s",
                inp.user_id, inp.coin, failed_checks, reason,
            )
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason=reason,
                skip=_STEP_NAMES[6:],
            )

        # ── Step 7: Final Decision (결정적 조립) ───────────────────────────────
        from agents.decision.final_decision import decide_final_action
        r7 = await _run_step(
            "final_decision",
            lambda: asyncio.to_thread(
                decide_final_action,
                candidate,
                ctx.ai_review,
                ctx.risk_result,
                getattr(inp, "decision_config", None),
            ),
        )
        if r7.failed:
            ctx.errors.append({"agent": "final_decision", "error": r7.error})
            logger.warning("[pipeline] final_decision 예외 — HOLD: %s", r7.error)
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason="최종 결정 단계 오류 — HOLD",
                skip=_STEP_NAMES[7:],
            )
        ctx.final_decision = r7.output
        if ctx.final_decision.action == FinalAction.HOLD:
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason=ctx.final_decision.reason,
                skip=_STEP_NAMES[7:],
            )

        # ── Step 8: Portfolio Manager ─────────────────────────────────────────
        new_risk = getattr(ctx.risk_result, "max_loss_usdt", Decimal("0")) or Decimal("0")
        r8 = await _run_step(
            "portfolio",
            lambda: asyncio.to_thread(
                self._deps.portfolio.can_add_position,
                inp.open_positions,
                inp.portfolio_account,
                new_risk,
            ),
        )
        if r8.failed:
            ctx.errors.append({"agent": "portfolio", "error": r8.error})
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason="PortfolioManager 실패 — 보수적 거부",
                skip=_STEP_NAMES[8:],
            )
        can_add, portfolio_reason = r8.output  # (bool, str)
        ctx.portfolio_check = r8.output
        if not can_add:
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason=portfolio_reason,
                skip=_STEP_NAMES[8:],
            )

        # ── Step 9: Position Manager ──────────────────────────────────────────
        user_id_str = inp.user_id or ""
        r9 = await _run_step(
            "position_manager",
            lambda: asyncio.to_thread(
                self._deps.position_manager.open,
                user_id_str,
                raw_signal,
                ctx.risk_result,
            ),
        )
        if r9.failed:
            ctx.errors.append({"agent": "position_manager", "error": r9.error})
            return _finish(
                PipelineStatus.FAILED,
                rejection_reason="PositionManager 실패",
                skip=_STEP_NAMES[9:],
            )
        ctx.position_state = r9.output

        # ── Step 10: Execution Engine ─────────────────────────────────────────
        from agents.execution.models import ExecutionRequest
        exec_req = ExecutionRequest(
            signal=raw_signal,
            user_ctx=inp.user_ctx,
            account=inp.account_state,
            daily_loss_usdt=inp.daily_loss_usdt or Decimal("0"),
            weekly_loss_usdt=inp.weekly_loss_usdt or Decimal("0"),
            weekly_limit_usdt=inp.weekly_limit_usdt or Decimal("0"),
            consecutive_losses=inp.consecutive_losses,
            open_positions_count=len(inp.open_positions),
            same_coin_position=same_coin,
            candidate=candidate,
            final_decision=ctx.final_decision,
            approved_validation=ctx.risk_result,
        )
        r10 = await _run_step(
            "execution",
            lambda: self._deps.execution.execute(exec_req),
        )
        if r10.failed:
            ctx.errors.append({"agent": "execution", "error": r10.error})
            return _finish(PipelineStatus.FAILED, rejection_reason="주문 실행 실패")
        ctx.execution_result = r10.output
        er = ctx.execution_result

        # ── TP/SL 실패 처리 (긴급 청산) ───────────────────────────────────────
        # engine.py가 재시도(1회) + 긴급 청산까지 처리한다.
        # 긴급 청산도 실패한 경우만 파이프라인이 FAILED를 반환한다.
        if er is not None and getattr(er, "emergency_close_failed", False):
            logger.critical(
                "emergency_close_failed user_id=%s coin=%s entry_id=%s "
                "— MANUAL INTERVENTION REQUIRED",
                inp.user_id, inp.coin,
                getattr(getattr(er, "entry_order", None), "exchange_order_id", "N/A"),
            )
            return _finish(
                PipelineStatus.FAILED,
                rejection_reason="TP/SL 실패 + 긴급 청산 실패 — 수동 개입 필요",
                execution_result=er,
            )

        if er is not None and getattr(er, "tp_sl_failed", False):
            # 긴급 청산 성공 — 포지션 안전하게 종료됨
            logger.warning(
                "tp_sl_failed_emergency_closed user_id=%s coin=%s",
                inp.user_id, inp.coin,
            )
            if self._deps.post_trade_hook is not None:
                await _fire_post_trade_hook(self._deps.post_trade_hook, inp, ctx)
            if self._deps.alert_dispatcher is not None:
                await _fire_emergency_alert(self._deps.alert_dispatcher, inp, ctx)
            return _finish(
                PipelineStatus.EMERGENCY_CLOSED,
                rejection_reason="TP/SL 설정 실패 — 긴급 청산 완료",
                execution_result=er,
            )

        return _finish(PipelineStatus.COMPLETED, execution_result=er)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _append_skipped(
    steps: list[AgentResult],
    names: list[str],
    reason: str = "",
) -> None:
    # 이미 기록된 스텝은 중복으로 추가하지 않는다.
    recorded = {s.agent_name for s in steps}
    for name in names:
        if name in recorded:
            continue
        s = AgentResult(agent_name=name)
        s.mark_skipped(reason)
        steps.append(s)


def _candidate_hold_reason(candidate: Any) -> str:
    if candidate is None:
        return "후보 없음 — HOLD"
    reasons = getattr(candidate, "reasons", None) or []
    if reasons:
        return str(reasons[-1])
    return "candidate.action=HOLD — 실행 없음"


def _review_action(ai_review: Any) -> Any:
    return getattr(ai_review, "review_action", None)


def _safe_reject_review(error: str) -> Any:
    """AI 리뷰 단계 실패 시 사용할 안전 REJECT 결과."""
    from agents.decision.models import AIReviewAction, AIReviewResult
    return AIReviewResult(
        review_action=AIReviewAction.REJECT,
        confidence=0.0,
        critical_contradiction=True,
        risk_warnings=["ai_review_failed"],
        reason_summary=f"AI review failed: {error}",
    )


def _build_review_input(symbol: str, decision_result: Any, candidate: Any) -> Any:
    """DecisionResult + TradeCandidate → ReviewInput (간결한 검토 컨텍스트)."""
    from agents.synthesis.models import ReviewInput

    regime = getattr(decision_result, "regime", None)
    chart = getattr(decision_result, "chart_score", None)
    news = getattr(decision_result, "news_score", None)
    deriv = getattr(decision_result, "derivatives_score", None)

    def _f(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    regime_name = getattr(getattr(regime, "regime", None), "value", None) or "UNKNOWN"

    return ReviewInput(
        coin=candidate.coin,
        symbol=symbol,
        market_regime=regime_name,
        regime_confidence=float(getattr(regime, "confidence", 0.0) or 0.0),
        chart_long_score=float(getattr(chart, "long_score", 0.0) or 0.0),
        chart_short_score=float(getattr(chart, "short_score", 0.0) or 0.0),
        chart_risk_score=float(getattr(chart, "risk_score", 0.0) or 0.0),
        chart_reasons=list(getattr(chart, "reasons", []) or []),
        news_sentiment_score=float(getattr(news, "sentiment_score", 0.0) or 0.0),
        news_risk_score=float(getattr(news, "risk_score", 0.0) or 0.0),
        news_no_trade_flag=bool(getattr(news, "no_trade_flag", False)),
        news_reasons=list(getattr(news, "reasons", []) or []),
        deriv_risk_score=float(getattr(deriv, "risk_score", 0.0) or 0.0),
        deriv_crowded_side=str(getattr(deriv, "crowded_side", "NONE") or "NONE"),
        deriv_reasons=list(getattr(deriv, "reasons", []) or []),
        strategy_type=getattr(candidate.strategy_type, "value", "UNKNOWN"),
        expected_holding_minutes=int(candidate.expected_holding_minutes or 0),
        action=getattr(candidate.action, "value", "HOLD"),
        entry_price=_f(candidate.entry_price) or 0.0,
        stop_loss=_f(candidate.stop_loss),
        take_profit=_f(candidate.take_profit),
        leverage=int(candidate.leverage or 0),
        notional_size=_f(candidate.notional_size) or 0.0,
        margin_ratio=float(candidate.margin_ratio or 0.0),
        actual_rr=float(candidate.actual_rr or 0.0),
        min_required_rr=float(candidate.min_required_rr or 0.0),
        expected_net_profit=_f(candidate.expected_net_profit),
        expected_net_loss=_f(candidate.expected_net_loss),
        spread_bps=float(candidate.spread_bps or 0.0),
        slippage_bps=float(candidate.slippage_bps or 0.0),
        liquidation_price=_f(candidate.liquidation_price),
    )


def _build_raw_signal_from_candidate(
    coin: str,
    symbol: str,
    candidate: Any,
    confidence: float,
) -> Any:
    """
    결정적 TradeCandidate → RawSignal (legacy PositionManager / Execution 호환).

    confidence는 차트 우세 점수 기반 결정적 값이며 AI 산출물이 아니다.
    방향/진입가/TP/SL/레버리지는 모두 candidate에서만 가져온다.
    """
    from agents.risk.models import RawSignal

    return RawSignal(
        direction=candidate.action.value,
        coin=coin,
        symbol=symbol,
        confidence=float(confidence),
        entry_price=candidate.entry_price,
        take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss,
        leverage=candidate.leverage,
    )


def _neutral_ta_result() -> Any:
    """TechnicalAnalysisAgent 실패 시 사용할 중립 결과."""
    from agents.technical_analysis.models import TechnicalAnalysisResult
    return TechnicalAnalysisResult(
        coin="UNKNOWN",
        symbol="UNKNOWNUSDT",
        tech_score=0.0,
        timeframe_scores={},
        analyses={},
        signals_fired=[],
        support_levels=[],
        resistance_levels=[],
        latest_close=0.0,
    )


def _neutral_strategy_signal() -> Any:
    """StrategyEngine 실패 시 사용할 중립 결과."""
    from agents.strategy.models import AggregatedSignal
    return AggregatedSignal(
        direction="NO_TRADE",
        confidence=0.0,
        entry=Decimal("0"),
        take_profit=None,
        stop_loss=None,
        leverage=1,
        rr_ratio=0.0,
        reasons=["strategy_engine_failed"],
        contributing_strategies=[],
    )


def _find_same_coin_position(positions: list[Any], coin: str) -> Any | None:
    """오픈 포지션 중 같은 코인 포지션 반환."""
    for p in positions:
        if getattr(p, "coin", None) == coin or getattr(p, "symbol", "").startswith(coin):
            return p
    return None


async def _fire_post_trade_hook(
    hook: PostTradeHookProvider,
    inp: PipelineInput,
    ctx: PipelineContext,
) -> None:
    """
    포지션 즉시 청산(EMERGENCY_CLOSED) 후 PostTradeHookProvider.on_trade_executed() 호출.

    COMPLETED 경로에서는 호출하지 않는다 — 포지션이 열려 있어 P&L이 확정되지 않았기 때문이다.
    """
    try:
        er = ctx.execution_result
        entry_order = getattr(er, "entry_order", None)
        if entry_order is None:
            return

        raw = ctx.raw_signal
        balance    = float(getattr(inp.account_state, "balance", 0) or 0)
        daily_loss = float(inp.daily_loss_usdt  or 0)
        weekly_loss= float(inp.weekly_loss_usdt or 0)
        max_loss   = float(getattr(ctx.risk_result, "max_loss_usdt", 0) or 0)
        direction  = getattr(raw, "direction", "LONG") if raw else "LONG"

        realized_pnl: Optional[float] = None
        emergency_close_order = getattr(er, "emergency_close_order", None)
        if emergency_close_order is not None:
            entry_px = Decimal(str(getattr(entry_order, "avg_fill_price", "0")))
            exit_px  = Decimal(str(getattr(emergency_close_order, "avg_fill_price", str(entry_px))))
            qty      = Decimal(str(getattr(entry_order, "quantity", "0")))
            if direction == "LONG":
                realized_pnl = float((exit_px - entry_px) * qty)
            else:  # SHORT
                realized_pnl = float((entry_px - exit_px) * qty)

        event = PostTradeEvent(
            user_id=inp.user_id or "",
            coin=inp.coin,
            direction=direction,
            entry_price=getattr(entry_order, "avg_fill_price", Decimal("0")),
            quantity=getattr(entry_order, "quantity", Decimal("0")),
            stop_loss=getattr(raw, "stop_loss", None) if raw else None,
            max_loss_usdt=max_loss,
            realized_pnl_usdt=realized_pnl,
            period_start_balance=balance + daily_loss,
            week_start_balance=balance + weekly_loss,
            current_balance=balance,
        )
        await hook.on_trade_executed(event)
    except Exception:
        logger.exception(
            "post_trade_hook error — pipeline not affected user=%s coin=%s",
            inp.user_id, inp.coin,
        )


async def _fire_emergency_alert(
    dispatcher: AlertDispatcherProvider,
    inp: PipelineInput,
    ctx: PipelineContext,
) -> None:
    """
    EMERGENCY_CLOSED 발생 시 AlertDispatcher로 Telegram 알림 발송.

    실패해도 EMERGENCY_CLOSED 결과에 영향을 주지 않는다.
    """
    try:
        from agents.alert.models import EmergencyClosedEvent

        er          = ctx.execution_result
        entry_order = getattr(er, "entry_order", None)
        if entry_order is None:
            return

        emergency_order = getattr(er, "emergency_close_order", None)
        exit_price = (
            getattr(emergency_order, "avg_fill_price", None)
            if emergency_order is not None
            else None
        ) or getattr(entry_order, "avg_fill_price", Decimal("0"))

        raw       = ctx.raw_signal
        symbol    = f"{inp.coin}USDT"
        direction = getattr(raw, "direction", "LONG") if raw else "LONG"

        event = EmergencyClosedEvent(
            symbol=symbol,
            direction=direction,
            entry_price=getattr(entry_order, "avg_fill_price", Decimal("0")),
            exit_price=exit_price,
            reason="TP/SL 설정 실패 — 긴급 청산 완료",
            triggered_at=datetime.now(timezone.utc),
        )
        await dispatcher.dispatch(event)
    except Exception:
        logger.exception(
            "emergency_alert error — pipeline not affected user=%s coin=%s",
            inp.user_id, inp.coin,
        )
