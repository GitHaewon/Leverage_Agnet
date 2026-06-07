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
from decimal import Decimal
from typing import Any

from celery import Task

from app.workers.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 의존성 조립 ──────────────────────────────────────────────────────────────

def _build_deps() -> "OrchestratorDeps":
    """실제 에이전트를 OrchestratorPipeline에 주입한다."""
    from agents.orchestrator.pipeline import OrchestratorDeps
    from agents.market_data.agent import MarketDataAgent
    from agents.technical_analysis.agent import TechnicalAnalysisAgent
    from agents.strategy.engine import StrategyEngine
    from agents.ai_analyst.agent import AIAnalystAgent
    from agents.risk.engine import RiskEngine
    from agents.portfolio.engine import PortfolioEngine
    from agents.position.manager import PositionManager
    from agents.execution.engine import ExecutionEngine

    return OrchestratorDeps(
        market_data=MarketDataAgent(),
        technical=TechnicalAnalysisAgent(),
        strategy=StrategyEngine(),
        analyst=AIAnalystAgent(),
        risk=RiskEngine(),
        portfolio=PortfolioEngine(),
        position_manager=PositionManager(),
        execution=ExecutionEngine(),
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
    return asyncio.run(_run_cycle_async(symbols))


async def _run_cycle_async(symbols: list[str]) -> dict[str, Any]:
    from app.services.user_service import get_auto_trading_users
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PipelineInput

    deps = _build_deps()
    pipeline = OrchestratorPipeline(deps)

    results: dict[str, Any] = {}

    users = await get_auto_trading_users()
    logger.info("analysis_cycle started: %d users × %d symbols", len(users), len(symbols))

    for user in users:
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
            )
            try:
                result = await pipeline.run(inp)
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
    return asyncio.run(_run_single_async(user_id, coin, user_ctx))


async def _run_single_async(
    user_id: str,
    coin: str,
    user_ctx_dict: dict | None,
) -> dict[str, Any]:
    from app.services.user_service import get_user_context
    from agents.orchestrator.pipeline import OrchestratorPipeline
    from agents.orchestrator.models import PipelineInput

    deps = _build_deps()
    pipeline = OrchestratorPipeline(deps)

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
    )
    result = await pipeline.run(inp)
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


@celery_app.task(
    name="app.workers.analysis_worker.expire_signals",
    acks_late=True,
)
def expire_signals() -> None:
    """만료된 시그널 정리 — beat_schedule에서 1분마다 실행."""
    asyncio.run(_expire_signals_async())


async def _expire_signals_async() -> None:
    from app.services.signal_service import expire_old_signals
    expired = await expire_old_signals()
    if expired:
        logger.info("expired %d signals", expired)
