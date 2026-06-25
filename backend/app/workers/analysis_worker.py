"""
Analysis Worker — Celery 태스크로 OrchestratorPipeline을 실행한다.

트리거 방식:
  1. beat_schedule: 5분마다 자동 실행 (run_analysis_cycle)
  2. API 엔드포인트: 수동 시그널 요청 (run_signal_for_user)
  3. Redis Streams: 캔들 마감 이벤트 소비 (consume_candle_close_events)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from celery import Task

from app.workers.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


def _shadow_decision_config() -> dict[str, Any] | None:
    """Shadow mode 전용 DecisionEngine 완화 프로파일.

    LIVE_TRADING_ENABLED=true일 때는 절대 적용하지 않는다.
    값이 설정되지 않은 threshold는 기존 live 기본 상수를 그대로 사용한다.
    """
    if settings.LIVE_TRADING_ENABLED or not settings.SHADOW_TRADING_ENABLED:
        return None

    cfg: dict[str, Any] = {
        "ai_review_required": bool(settings.SHADOW_AI_REVIEW_REQUIRED),
        "profile": "shadow",
    }
    if settings.SHADOW_MIN_LONG_SCORE is not None:
        cfg["min_long_score"] = float(settings.SHADOW_MIN_LONG_SCORE)
    if settings.SHADOW_MIN_SHORT_SCORE is not None:
        cfg["min_short_score"] = float(settings.SHADOW_MIN_SHORT_SCORE)
    if settings.SHADOW_MAX_RISK_SCORE is not None:
        shadow_risk = float(settings.SHADOW_MAX_RISK_SCORE)
        cfg["max_risk_score"] = shadow_risk        # candidate_generator gate
        cfg["max_risk_trend"] = shadow_risk        # strategy_selector TREND
        cfg["max_risk_breakout"] = shadow_risk     # strategy_selector BREAKOUT
        cfg["max_risk_intraday"] = shadow_risk     # strategy_selector INTRADAY
        cfg["max_risk_scalping"] = shadow_risk     # strategy_selector SCALPING
    return cfg


# ── 의존성 조립 ──────────────────────────────────────────────────────────────

async def _build_deps(
    redis: "Any",
    user_id: uuid.UUID | None = None,
    session: "Any | None" = None,
) -> "OrchestratorDeps":
    """
    실제 에이전트를 OrchestratorPipeline에 주입한다.

    LIVE_TRADING_ENABLED=true + user_id : BinanceGateway (실거래/테스트넷)
    SHADOW_TRADING_ENABLED=true         : ShadowExecutionEngine (가상 체결 기록)
    그 외 (paper)                        : ExecutionEngine + PaperGateway
    """
    from agents.orchestrator.pipeline import OrchestratorDeps
    from agents.market_data.agent import MarketDataAgent
    from agents.technical_analysis.agent import TechnicalAnalysisAgent
    from agents.strategy.engine import StrategyEngine
    from agents.decision.engine import DecisionEngine
    from agents.synthesis.agent import ReviewerAgent
    from agents.analyst.agent import OpenAIClient
    from agents.risk.engine import RiskEngine
    from agents.portfolio.engine import PortfolioEngine
    from agents.position_manager.engine import PositionManagerEngine
    from agents.execution.engine import ExecutionEngine
    from agents.execution.gateway import PaperGateway

    risk_engine = RiskEngine(redis=redis)
    safety_gate = None

    if settings.LIVE_TRADING_ENABLED and user_id is not None:
        from app.gateways.binance_gateway import BinanceGateway
        from app.safety import RedisSafetyStateStore, SafetyConfig, SafetyGate
        from app.safety.adapter import SafetyGateAdapter
        gateway = BinanceGateway(
            user_id=user_id,
            is_testnet=settings.BINANCE_TESTNET,
        )
        mode = "testnet" if settings.BINANCE_TESTNET else "live"
        safety_gate = SafetyGateAdapter(
            SafetyGate(
                store=RedisSafetyStateStore(redis),
                config=SafetyConfig(live_trading_enabled=True),
            )
        )
        execution = ExecutionEngine(
            risk_validator=risk_engine,
            gateway=gateway,
            live_trading_enabled=True,
            mode=mode,
            safety_gate=safety_gate,
        )
    elif settings.SHADOW_TRADING_ENABLED:
        # Shadow mode: ShadowExecutionEngine — Risk 검증 동일, 가상 체결을 DB에 저장
        from agents.shadow.execution import ShadowExecutionEngine
        from app.repositories.shadow_trade_repository import ShadowTradeRepository
        execution = ShadowExecutionEngine(
            risk_validator=risk_engine,
            store=ShadowTradeRepository(session),
        )
    else:
        # Paper mode: 주문 실행 없음, 시그널 로직 검증 전용
        execution = ExecutionEngine(
            risk_validator=risk_engine,
            gateway=PaperGateway(),
            live_trading_enabled=False,
            mode="paper",
            safety_gate=None,
        )

    # AlertDispatcher: bot_token + chat_id가 모두 설정된 경우에만 생성
    alert_dispatcher = None
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        from agents.alert.dispatcher import AlertDispatcher
        from agents.alert.sender import TelegramSender
        alert_dispatcher = AlertDispatcher(
            sender=TelegramSender(bot_token=settings.TELEGRAM_BOT_TOKEN),
            chat_id=settings.TELEGRAM_CHAT_ID,
        )

    return OrchestratorDeps(
        market_data=MarketDataAgent(redis=redis),
        technical=TechnicalAnalysisAgent(),
        strategy=StrategyEngine(),
        decision=DecisionEngine(),
        reviewer=ReviewerAgent(
            client=OpenAIClient(api_key=settings.OPENAI_API_KEY),
            model=settings.OPENAI_MODEL,
        ),
        risk=risk_engine,
        portfolio=PortfolioEngine(),
        position_manager=PositionManagerEngine(),
        execution=execution,
        post_trade_hook=safety_gate,  # SafetyGateAdapter: 체결 후 kill switch 손실 누적
        alert_dispatcher=alert_dispatcher,
    )


# ── Celery 태스크 ─────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.analysis_worker.run_analysis_cycle",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def run_analysis_cycle(self: Task, symbols: list[str]) -> dict[str, Any]:
    """
    자동매매 사이클 — 전체 활성 사용자 × 요청 심볼 조합으로 파이프라인 실행.

    beat_schedule에서 5분마다 트리거된다.
    개별 사용자 파이프라인 실패는 다른 사용자에게 영향을 주지 않는다.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_cycle_async(symbols))
    finally:
        loop.close()


async def _run_cycle_async(symbols: list[str]) -> dict[str, Any]:
    import redis.asyncio as aioredis
    from app.services.user_service import get_auto_trading_users
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PipelineInput

    redis_client = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)
    try:
        results: dict[str, Any] = {}
        users = await get_auto_trading_users()
        logger.info("analysis_cycle started: %d users × %d symbols", len(users), len(symbols))

        # Paper mode: AI 에이전트는 사용자 무관 → 파이프라인 한 번만 구성 (최적화)
        # Shadow/Live mode: 세션/게이트웨이가 사용자·심볼별로 다름 → 심볼별 재구성
        shared_pipeline: OrchestratorPipeline | None = None
        if not settings.LIVE_TRADING_ENABLED and not settings.SHADOW_TRADING_ENABLED:
            shared_deps = await _build_deps(redis_client)
            shared_pipeline = OrchestratorPipeline(shared_deps)

        for user in users:
            live_pipeline: OrchestratorPipeline | None = None
            if settings.LIVE_TRADING_ENABLED:
                user_deps = await _build_deps(redis_client, user_id=user.id)
                live_pipeline = OrchestratorPipeline(user_deps)

            for symbol in symbols:
                coin = symbol.replace("USDT", "")
                inp = PipelineInput(
                    coin=coin,
                    user_id=str(user.id),
                    user_ctx=user,
                    account_state=user.account_state,
                    daily_loss_usdt=user.daily_loss_usdt or Decimal("0"),
                    weekly_loss_usdt=user.weekly_loss_usdt or Decimal("0"),
                    weekly_limit_usdt=user.weekly_limit_usdt or Decimal("500"),
                    consecutive_losses=user.consecutive_losses,
                    open_positions=user.open_positions or [],
                    portfolio_account=user.portfolio_account,
                    decision_config=_shadow_decision_config(),
                )
                try:
                    if settings.LIVE_TRADING_ENABLED:
                        result = await live_pipeline.run(inp)  # type: ignore[union-attr]
                    elif settings.SHADOW_TRADING_ENABLED:
                        # NullPool 엔진으로 새 세션 생성 — asyncio.run() event loop 경계 문제 방지
                        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
                        from sqlalchemy.pool import NullPool
                        from agents.orchestrator.logger import OrchestratorLogger
                        from app.repositories.shadow_decision_repository import ShadowDecisionRepository
                        _engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
                        try:
                            _sf = async_sessionmaker(
                                _engine, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False
                            )
                            async with _sf() as trade_session, _sf() as decision_session:
                                shadow_deps = await _build_deps(
                                    redis_client,
                                    session=trade_session,
                                )
                                result = await OrchestratorPipeline(
                                    shadow_deps,
                                    orch_logger=OrchestratorLogger(
                                        ShadowDecisionRepository(decision_session)
                                    ),
                                ).run(inp)
                                await trade_session.commit()
                                try:
                                    await decision_session.commit()
                                except Exception:
                                    await decision_session.rollback()
                                    logger.exception(
                                        "shadow_decision commit failed user=%s coin=%s",
                                        user.id,
                                        coin,
                                    )
                        finally:
                            await _engine.dispose()
                    else:
                        result = await shared_pipeline.run(inp)  # type: ignore[union-attr]
                    results[f"{user.id}:{coin}"] = {
                        "status": result.status,
                        "run_id": result.run_id,
                    }
                    logger.info(
                        "pipeline done user=%s coin=%s status=%s run_id=%s",
                        user.id, coin, result.status, result.run_id,
                    )
                except Exception as exc:
                    # 개별 사용자 실패는 격리 — 다음 사용자 계속 진행
                    logger.exception("pipeline error user=%s coin=%s: %s", user.id, coin, exc)
                    results[f"{user.id}:{coin}"] = {"status": "error", "error": str(exc)}

        return results
    finally:
        await redis_client.aclose()


@celery_app.task(
    name="app.workers.analysis_worker.run_signal_for_user",
    bind=True,
    max_retries=1,
    default_retry_delay=10,
    acks_late=True,
)
def run_signal_for_user(
    self: Task,
    user_id: str,
    coin: str,
    user_ctx: dict | None = None,
) -> dict[str, Any]:
    """
    수동 시그널 요청 — API 엔드포인트에서 특정 사용자·코인에 대해 즉시 호출.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_single_async(user_id, coin, user_ctx))
    finally:
        loop.close()


async def _run_single_async(
    user_id: str,
    coin: str,
    user_ctx_dict: dict | None,
) -> dict[str, Any]:
    import redis.asyncio as aioredis
    from app.services.user_service import get_user_context
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PipelineInput

    redis_client = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)
    try:
        uid = uuid.UUID(user_id)
        user = await get_user_context(user_id)
        inp = PipelineInput(
            coin=coin,
            user_id=user_id,
            user_ctx=user,
            account_state=user.account_state,
            daily_loss_usdt=user.daily_loss_usdt or Decimal("0"),
            weekly_loss_usdt=user.weekly_loss_usdt or Decimal("0"),
            weekly_limit_usdt=user.weekly_limit_usdt or Decimal("500"),
            consecutive_losses=user.consecutive_losses,
            open_positions=user.open_positions or [],
            portfolio_account=user.portfolio_account,
            decision_config=_shadow_decision_config(),
        )

        if settings.SHADOW_TRADING_ENABLED and not settings.LIVE_TRADING_ENABLED:
            from agents.orchestrator.logger import OrchestratorLogger
            from app.core.database import AsyncSessionLocal
            from app.repositories.shadow_decision_repository import ShadowDecisionRepository
            async with AsyncSessionLocal() as trade_session, AsyncSessionLocal() as decision_session:
                deps = await _build_deps(redis_client, session=trade_session)
                result = await OrchestratorPipeline(
                    deps,
                    orch_logger=OrchestratorLogger(
                        ShadowDecisionRepository(decision_session)
                    ),
                ).run(inp)
                await trade_session.commit()
                try:
                    await decision_session.commit()
                except Exception:
                    await decision_session.rollback()
                    logger.exception(
                        "shadow_decision commit failed user=%s coin=%s",
                        user_id,
                        coin,
                    )
        else:
            deps = await _build_deps(redis_client, user_id=uid)
            result = await OrchestratorPipeline(deps).run(inp)
        return {
            "run_id": result.run_id,
            "status": result.status,
            "coin": result.coin,
            "rejection_reason": result.rejection_reason,
            "total_latency_ms": result.total_latency_ms,
            "steps": [
                {
                    "name": s.agent_name,
                    "status": s.status,
                    "latency_ms": s.latency_ms,
                    "error": s.error,
                }
                for s in result.steps
            ],
        }
    finally:
        await redis_client.aclose()


@celery_app.task(
    name="app.workers.analysis_worker.expire_signals",
    acks_late=True,
)
def expire_signals() -> None:
    """만료된 시그널 정리 — beat_schedule에서 1분마다 실행."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_expire_signals_async())
    finally:
        loop.close()


async def _expire_signals_async() -> None:
    from app.services.signal_service import expire_old_signals
    expired = await expire_old_signals()
    if expired:
        logger.info("expired %d signals", expired)
