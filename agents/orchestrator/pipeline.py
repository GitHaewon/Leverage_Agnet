"""
Agent Orchestrator Pipeline.

8개 에이전트를 순서대로 실행하며, 각 단계 실패가 전체를 멈추지 않도록 격리한다.

실행 순서:
  1. MarketDataAgent      CRITICAL  실패 → FAILED
  2. TechnicalAnalysis    DEGRADED  실패 → 중립값(tech_score=0.0)으로 계속
  3. StrategyEngine       DEGRADED  실패 → 중립값으로 계속
  4. AIAnalystAgent       CRITICAL  실패 → FAILED / HOLD → 이후 스텝 skip
  5. RiskEngine           GATE      실패 → 보수적 REJECT
  6. PortfolioManager     GATE      실패 → 보수적 REJECT
  7. PositionManager      실패 → FAILED
  8. ExecutionEngine      실패 → FAILED (retry=3)

안전 원칙 (CLAUDE.md):
  - RiskEngine 실패 기본값 = 거부 (실행하지 않음)
  - 손절 없는 시그널은 RawSignal 생성 시점에 None-guard
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
    AgentStatus,
    PipelineContext,
    PipelineInput,
    PipelineResult,
    PipelineStatus,
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
class AnalystProvider(Protocol):
    """AIAnalystAgent(Synthesis) 인터페이스."""
    async def analyze(
        self,
        market: Any,
        technical: Any,
        strategy: Any,
    ) -> Any: ...


@runtime_checkable
class RiskProvider(Protocol):
    """RiskEngine 인터페이스."""
    async def validate(
        self,
        signal: Any,
        user_ctx: Any,
        account: Any,
        *,
        daily_loss_usdt: Any = None,
        weekly_loss_usdt: Any = None,
        weekly_limit_usdt: Any = None,
        consecutive_losses: int = 0,
        open_positions_count: int = 0,
        same_coin_position: Any = None,
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


# ── 스텝 설정 ──────────────────────────────────────────────────────────────────

_STEP_TIMEOUT: dict[str, float] = {
    "market_data":       10.0,
    "technical":         10.0,
    "strategy":           5.0,
    "ai_analyst":        30.0,   # Claude API 포함
    "risk":               5.0,
    "portfolio":          3.0,
    "position_manager":   3.0,
    "execution":         15.0,
}

_STEP_RETRIES: dict[str, int] = {
    "market_data":        2,
    "technical":          1,
    "strategy":           1,
    "ai_analyst":         1,
    "risk":               0,    # 실패 시 즉시 보수적 거부
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
    analyst:          AnalystProvider
    risk:             RiskProvider
    portfolio:        PortfolioProvider
    position_manager: PositionManagerProvider
    execution:        ExecutionProvider


# ── OrchestratorPipeline ──────────────────────────────────────────────────────

class OrchestratorPipeline:
    """
    8-step 에이전트 순차 실행 파이프라인.

    사용 예:
        deps   = OrchestratorDeps(market_data=..., technical=..., ...)
        pipeline = OrchestratorPipeline(deps)
        result = await pipeline.run(PipelineInput(coin="BTC", user_id="...", ...))
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
                skip=["technical", "strategy", "ai_analyst",
                      "risk", "portfolio", "position_manager", "execution"],
            )
        ctx.market_snapshot = r1.output
        snap: dict = ctx.market_snapshot

        # ── Step 2: Technical Analysis ────────────────────────────────────────
        ohlcv = snap.get("ohlcv", {})
        r2 = await _run_step(
            "technical",
            lambda: asyncio.to_thread(
                self._deps.technical.run,
                ohlcv,
                inp.coin,
                f"{inp.coin}USDT",
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
        strategy_inp = StrategyInput(
            coin=inp.coin,
            symbol=f"{inp.coin}USDT",
            current_price=Decimal(str(snap.get("current_price", "0"))),
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

        # ── Step 4: AI Analyst ────────────────────────────────────────────────
        from agents.analyst.models import MarketContext, TechnicalContext, StrategyContext
        market_ctx = MarketContext(
            coin=inp.coin,
            symbol=f"{inp.coin}USDT",
            current_price=float(snap.get("current_price", 0.0)),
        )
        tech_ctx = _build_tech_context(ctx.tech_result)
        strategy_ctx = _build_strategy_context(ctx.strategy_signal)

        r4 = await _run_step(
            "ai_analyst",
            lambda: self._deps.analyst.analyze(market_ctx, tech_ctx, strategy_ctx),
        )
        if r4.failed:
            ctx.errors.append({"agent": "ai_analyst", "error": r4.error})
            return _finish(
                PipelineStatus.FAILED,
                rejection_reason="AI 분석 실패",
                skip=["risk", "portfolio", "position_manager", "execution"],
            )
        ctx.analyst_result = r4.output

        # HOLD 판정 → 이후 스텝 불필요
        if not ctx.analyst_result.is_actionable:
            hold_reason = getattr(ctx.analyst_result, "hold_reason", "") or "HOLD"
            return _finish(
                PipelineStatus.HOLD,
                rejection_reason=hold_reason,
                skip=["risk", "portfolio", "position_manager", "execution"],
            )

        # ── RawSignal 생성 (이후 스텝 공통 입력) ────────────────────────────
        from agents.risk.models import RawSignal
        raw_signal = _build_raw_signal(inp.coin, ctx.analyst_result)

        # ── Step 5: Risk Engine ───────────────────────────────────────────────
        same_coin = _find_same_coin_position(inp.open_positions, inp.coin)
        r5 = await _run_step(
            "risk",
            lambda: self._deps.risk.validate(
                raw_signal,
                inp.user_ctx,
                inp.account_state,
                daily_loss_usdt=inp.daily_loss_usdt,
                weekly_loss_usdt=inp.weekly_loss_usdt,
                weekly_limit_usdt=inp.weekly_limit_usdt,
                consecutive_losses=inp.consecutive_losses,
                open_positions_count=len(inp.open_positions),
                same_coin_position=same_coin,
            ),
        )
        if r5.failed:
            ctx.errors.append({"agent": "risk", "error": r5.error})
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason="RiskEngine 실패 — 보수적 거부",
                skip=["portfolio", "position_manager", "execution"],
            )
        ctx.risk_result = r5.output
        if not ctx.risk_result.approved:
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason=ctx.risk_result.rejection_reason,
                skip=["portfolio", "position_manager", "execution"],
            )

        # ── Step 6: Portfolio Manager ─────────────────────────────────────────
        new_risk = getattr(ctx.risk_result, "max_loss_usdt", Decimal("0")) or Decimal("0")
        r6 = await _run_step(
            "portfolio",
            lambda: asyncio.to_thread(
                self._deps.portfolio.can_add_position,
                inp.open_positions,
                inp.portfolio_account,
                new_risk,
            ),
        )
        if r6.failed:
            ctx.errors.append({"agent": "portfolio", "error": r6.error})
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason="PortfolioManager 실패 — 보수적 거부",
                skip=["position_manager", "execution"],
            )
        can_add, portfolio_reason = r6.output  # (bool, str)
        ctx.portfolio_check = r6.output
        if not can_add:
            return _finish(
                PipelineStatus.REJECTED,
                rejection_reason=portfolio_reason,
                skip=["position_manager", "execution"],
            )

        # ── Step 7: Position Manager ──────────────────────────────────────────
        user_id_str = inp.user_id or ""
        r7 = await _run_step(
            "position_manager",
            lambda: asyncio.to_thread(
                self._deps.position_manager.open,
                user_id_str,
                raw_signal,
                ctx.risk_result,
            ),
        )
        if r7.failed:
            ctx.errors.append({"agent": "position_manager", "error": r7.error})
            return _finish(
                PipelineStatus.FAILED,
                rejection_reason="PositionManager 실패",
                skip=["execution"],
            )
        ctx.position_state = r7.output

        # ── Step 8: Execution Engine ──────────────────────────────────────────
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
        )
        r8 = await _run_step(
            "execution",
            lambda: self._deps.execution.execute(exec_req),
        )
        if r8.failed:
            ctx.errors.append({"agent": "execution", "error": r8.error})
            return _finish(PipelineStatus.FAILED, rejection_reason="주문 실행 실패")
        ctx.execution_result = r8.output

        return _finish(PipelineStatus.COMPLETED, execution_result=ctx.execution_result)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _append_skipped(
    steps: list[AgentResult],
    names: list[str],
    reason: str = "",
) -> None:
    for name in names:
        s = AgentResult(agent_name=name)
        s.mark_skipped(reason)
        steps.append(s)


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
    from decimal import Decimal
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


def _build_tech_context(tech_result: Any) -> Any:
    from agents.analyst.models import TechnicalContext
    return TechnicalContext(
        tech_score=getattr(tech_result, "tech_score", 0.0),
        timeframe_scores=getattr(tech_result, "timeframe_scores", {}),
        indicators=getattr(tech_result, "indicators", {}),
        signals_fired=getattr(tech_result, "signals_fired", []),
        support_levels=getattr(tech_result, "support_levels", []),
        resistance_levels=getattr(tech_result, "resistance_levels", []),
    )


def _build_strategy_context(strategy_signal: Any) -> Any:
    from agents.analyst.models import StrategyContext
    return StrategyContext(
        sentiment_score=getattr(strategy_signal, "sentiment_score", 0.0),
        fear_greed_index=getattr(strategy_signal, "fear_greed_index", 50),
        fear_greed_label=getattr(strategy_signal, "fear_greed_label", "Neutral"),
        dominant_sentiment=getattr(strategy_signal, "dominant_sentiment", "neutral"),
        news_items=getattr(strategy_signal, "news_items", []),
        market_score=getattr(strategy_signal, "market_score", 0.0),
        funding_rate=getattr(strategy_signal, "funding_rate", 0.0),
        oi_1h_change_pct=getattr(strategy_signal, "oi_1h_change_pct", 0.0),
        long_short_ratio=getattr(strategy_signal, "long_short_ratio", 1.0),
        long_account_pct=getattr(strategy_signal, "long_account_pct", 50.0),
        whale_activity=getattr(strategy_signal, "whale_activity", "neutral"),
    )


def _build_raw_signal(coin: str, analyst_result: Any) -> Any:
    """AnalystResult → RawSignal 변환."""
    from agents.risk.models import RawSignal
    decision = analyst_result.decision
    # AnalysisDecision.confidence 는 int(0~100); RawSignal 은 float(0.0~1.0)
    confidence_float = float(decision.confidence) / 100.0

    stop_loss_raw = analyst_result.stop_loss
    take_profit_raw = analyst_result.take_profit

    return RawSignal(
        direction=decision.decision,
        coin=coin,
        symbol=f"{coin}USDT",
        confidence=confidence_float,
        entry_price=Decimal(str(analyst_result.entry_price)),
        take_profit=Decimal(str(take_profit_raw)) if take_profit_raw is not None else None,
        stop_loss=Decimal(str(stop_loss_raw)) if stop_loss_raw is not None else None,
        leverage=analyst_result.leverage,
    )


def _find_same_coin_position(positions: list[Any], coin: str) -> Any | None:
    """오픈 포지션 중 같은 코인 포지션 반환."""
    for p in positions:
        if getattr(p, "coin", None) == coin or getattr(p, "symbol", "").startswith(coin):
            return p
    return None
