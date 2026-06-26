"""
Shadow Trade 모니터 워커.

30초마다 실행되어 OPEN shadow 거래를 현재가와 비교한다.
TP 또는 SL 도달 시 PnL·Duration을 계산하고 청산 처리한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.shadow_trade import ShadowTrade
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def check_and_close_shadow_trades(
    current_prices: dict[str, Decimal],
    session: AsyncSession,
) -> int:
    """
    OPEN shadow 거래를 현재가와 비교해 TP/SL 체결을 시뮬레이션한다.

    LONG:  current >= tp_price → TP_HIT
           current <= sl_price → SL_HIT
    SHORT: current <= tp_price → TP_HIT
           current >= sl_price → SL_HIT

    returns: 청산 처리된 거래 수
    """
    from app.repositories.shadow_trade_repository import ShadowTradeRepository

    repo = ShadowTradeRepository(session)
    open_trades: Sequence[ShadowTrade] = await repo.get_open_trades()
    logger.info(
        "shadow_monitor_check open_trades=%d price_symbols=%s",
        len(open_trades),
        sorted(current_prices.keys()),
    )
    closed = 0
    missing_prices = 0

    for trade in open_trades:
        current_price = current_prices.get(trade.symbol)
        if current_price is None:
            missing_prices += 1
            logger.warning(
                "shadow_monitor_missing_price trade_id=%s symbol=%s direction=%s",
                trade.id,
                trade.symbol,
                trade.direction,
            )
            continue

        exit_price: Decimal | None = None
        status: str | None = None

        if trade.direction == "LONG":
            if current_price >= trade.tp_price:
                exit_price, status = trade.tp_price, "TP_HIT"
            elif current_price <= trade.sl_price:
                exit_price, status = trade.sl_price, "SL_HIT"
        else:  # SHORT
            if current_price <= trade.tp_price:
                exit_price, status = trade.tp_price, "TP_HIT"
            elif current_price >= trade.sl_price:
                exit_price, status = trade.sl_price, "SL_HIT"

        if exit_price is None:
            continue

        now = datetime.now(timezone.utc)
        if trade.direction == "LONG":
            pnl = float((exit_price - trade.entry_price) * trade.quantity)
        else:
            pnl = float((trade.entry_price - exit_price) * trade.quantity)

        duration = (now - trade.opened_at).total_seconds()

        await repo.close_trade(
            trade_id=trade.id,
            exit_price=exit_price,
            pnl_usdt=pnl,
            duration_seconds=duration,
            status=status,
            closed_at=now,
        )
        closed += 1
        logger.info(
            "shadow_trade_closed id=%s symbol=%s direction=%s status=%s "
            "entry=%s exit=%s tp=%s sl=%s qty=%s pnl=%.4f duration=%.1fs",
            trade.id, trade.symbol, trade.direction, status,
            trade.entry_price, exit_price, trade.tp_price, trade.sl_price,
            trade.quantity, pnl, duration,
        )

    logger.info(
        "shadow_monitor_result checked=%d closed=%d missing_prices=%d",
        len(open_trades),
        closed,
        missing_prices,
    )
    return closed


@celery_app.task(
    name="app.workers.shadow_monitor_worker.run_shadow_monitor",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def run_shadow_monitor(self: Task) -> None:
    """Celery beat task — 30초 주기."""
    if not settings.SHADOW_TRADING_ENABLED:
        return

    from app.core.database import AsyncSessionLocal
    from app.workers.candle_consumer import get_latest_prices

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        # Celery 태스크마다 새 event loop에서 실행되므로 NullPool로 풀 재사용 방지
        _engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False
        )
        try:
            prices: dict[str, Decimal] = {
                k: Decimal(str(v))
                for k, v in (await get_latest_prices()).items()
            }
            async with _session_factory() as session:
                closed = await check_and_close_shadow_trades(prices, session)
                await session.commit()
                if closed:
                    logger.info("shadow_monitor: closed %d trades this cycle", closed)
        finally:
            await _engine.dispose()

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
    except Exception as exc:
        logger.error("shadow_monitor failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc, countdown=10)
