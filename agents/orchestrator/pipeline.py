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


@runtime_checkable
class PostTradeHookProvider(Protocol):
    """실거래 체결 후 SafetyGate 손실 누적 인터페이스."""
    async def on_trade_executed(self, event: PostTradeEvent) -> None: ...


@runtime_checkable
class AlertDispatcherProvider(Protocol):
    """긴급 청산 등 중요 이벤트를 Telegram으로 발송하는 인터페이스."""
    async def dispatch(self, event: Any) -> Any: ...


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
    post_trade_hook:  Optional[PostTradeHookProvider]  = None
    alert_dispatcher: Optional[AlertDispatcherProvider] = None


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
        ctx.raw_signal = raw_signal

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
        er = ctx.execution_result

        # ── TP/SL 실패 처리 ─────────────────────────────────────────────────
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
            # Post-Trade Hook: 긴급 청산도 완료된 거래 — kill switch 손실 누적 필요
            # entry 체결 후 즉시 청산됐으므로 max_loss_usdt(SL 기준 보수적 추정)로 누적
            if self._deps.post_trade_hook is not None:
                await _fire_post_trade_hook(self._deps.post_trade_hook, inp, ctx)
            # Alert: 사용자에게 긴급 청산 사실을 즉시 Telegram으로 통보
            if self._deps.alert_dispatcher is not None:
                await _fire_emergency_alert(self._deps.alert_dispatcher, inp, ctx)
            return _finish(
                PipelineStatus.EMERGENCY_CLOSED,
                rejection_reason="TP/SL 설정 실패 — 긴급 청산 완료",
                execution_result=er,
            )

        # COMPLETED: TP/SL 걸린 포지션이 아직 열려 있음 — 미실현 P&L로 kill switch 누적 금지.
        # 포지션이 실제로 닫히면(TP/SL 체결, 수동 청산) 모니터링 워커가 on_trade_closed()를 호출한다.

        return _finish(PipelineStatus.COMPLETED, execution_result=er)


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


async def _fire_post_trade_hook(
    hook: PostTradeHookProvider,
    inp: PipelineInput,
    ctx: PipelineContext,
) -> None:
    """
    포지션 즉시 청산(EMERGENCY_CLOSED) 후 PostTradeHookProvider.on_trade_executed() 호출.

    COMPLETED 경로에서는 호출하지 않는다 — 포지션이 열려 있어 P&L이 확정되지 않았기 때문이다.

    realized_pnl_usdt: emergency_close_order fill price로 계산한 확정 P&L.
      - LONG:  (exit_px - entry_px) * qty
      - SHORT: (entry_px - exit_px) * qty
    emergency_close_order가 없으면 None → Adapter가 max_loss_usdt fallback 사용.
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

        # 실제 fill price로 확정 P&L 계산 (emergency_close_order가 있을 때만)
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
    exit_price: 긴급 청산 체결가. 없으면 진입가를 fallback으로 사용.
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
