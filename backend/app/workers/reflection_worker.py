"""
Reflection Worker — 포지션 종료 후 ReflectionAgent를 Celery 태스크로 실행한다.

트리거 방식:
  1. Execution Agent → position_closed 이벤트 → trigger_reflection_for_position
  2. API 엔드포인트 → 수동 재실행 → trigger_reflection_for_position
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from celery import Task

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.reflection_worker.trigger_reflection_for_position",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def trigger_reflection_for_position(
    self: Task,
    position_id: str,
    user_id: str,
    coin: str,
    symbol: str,
    direction: str,
    leverage: int,
    entry_price: str,
    close_price: str,
    stop_loss: str,
    net_pnl: str,
    pnl_percentage: str,
    duration_seconds: int,
    close_reason: str,
    take_profit: str | None = None,
    signal_confidence: float | None = None,
    signal_reasons: list[str] | None = None,
    signal_rr_ratio: float | None = None,
    signal_entry_price: str | None = None,
    signal_tp: str | None = None,
    signal_sl: str | None = None,
    journal_id: str | None = None,
    user_max_leverage: int = 20,
    price_action_summary: str | None = None,
) -> dict:
    """
    포지션 종료 후 ReflectionAgent를 실행한다.

    모든 Decimal 값은 직렬화를 위해 str로 전달된다.
    태스크 실패 시 최대 3회 재시도 (60초 간격).
    """
    try:
        return asyncio.run(
            _run_reflection_async(
                position_id=position_id,
                user_id=user_id,
                coin=coin,
                symbol=symbol,
                direction=direction,
                leverage=leverage,
                entry_price=entry_price,
                close_price=close_price,
                stop_loss=stop_loss,
                net_pnl=net_pnl,
                pnl_percentage=pnl_percentage,
                duration_seconds=duration_seconds,
                close_reason=close_reason,
                take_profit=take_profit,
                signal_confidence=signal_confidence,
                signal_reasons=signal_reasons or [],
                signal_rr_ratio=signal_rr_ratio,
                signal_entry_price=signal_entry_price,
                signal_tp=signal_tp,
                signal_sl=signal_sl,
                journal_id=journal_id,
                user_max_leverage=user_max_leverage,
                price_action_summary=price_action_summary,
            )
        )
    except Exception as exc:
        logger.exception(
            "reflection task failed position=%s attempt=%d: %s",
            position_id, self.request.retries + 1, exc,
        )
        raise self.retry(exc=exc)


async def _run_reflection_async(
    position_id: str,
    user_id: str,
    **kwargs,
) -> dict:
    import uuid as _uuid
    from app.core.database import get_async_session
    from app.schemas.reflection import ReflectionInput
    from app.services.reflection_service import ReflectionService

    inp = ReflectionInput(
        position_id=_uuid.UUID(position_id),
        user_id=_uuid.UUID(user_id),
        journal_id=_uuid.UUID(kwargs["journal_id"]) if kwargs.get("journal_id") else None,
        coin=kwargs["coin"],
        symbol=kwargs["symbol"],
        direction=kwargs["direction"],
        leverage=kwargs["leverage"],
        entry_price=Decimal(kwargs["entry_price"]),
        close_price=Decimal(kwargs["close_price"]),
        stop_loss=Decimal(kwargs["stop_loss"]),
        take_profit=Decimal(kwargs["take_profit"]) if kwargs.get("take_profit") else None,
        net_pnl=Decimal(kwargs["net_pnl"]),
        pnl_percentage=Decimal(kwargs["pnl_percentage"]),
        duration_seconds=kwargs["duration_seconds"],
        close_reason=kwargs["close_reason"],
        signal_confidence=kwargs.get("signal_confidence"),
        signal_reasons=kwargs.get("signal_reasons") or [],
        signal_rr_ratio=kwargs.get("signal_rr_ratio"),
        signal_entry_price=Decimal(kwargs["signal_entry_price"]) if kwargs.get("signal_entry_price") else None,
        signal_tp=Decimal(kwargs["signal_tp"]) if kwargs.get("signal_tp") else None,
        signal_sl=Decimal(kwargs["signal_sl"]) if kwargs.get("signal_sl") else None,
        user_max_leverage=kwargs.get("user_max_leverage", 20),
        price_action_summary=kwargs.get("price_action_summary"),
    )

    async with get_async_session() as db:
        service = ReflectionService(db)
        report = await service.run_and_save(inp)
        await db.commit()

    logger.info(
        "reflection complete position=%s grade=%s violations=%d",
        position_id, report.ai_grade, len(report.risk_rule_violations),
    )

    return {
        "report_id": str(report.id),
        "position_id": position_id,
        "ai_grade": report.ai_grade,
        "risk_violations_count": len(report.risk_rule_violations),
    }
