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
from agents.shadow.pnl import ShadowCostConfig, calculate_shadow_pnl

logger = logging.getLogger(__name__)


def _decimal_cost(value: object) -> Decimal:
    if isinstance(value, (Decimal, int, float, str)):
        try:
            return Decimal(str(value))
        except Exception:
            pass
    return Decimal("0")


async def check_and_close_shadow_trades(
    current_prices: dict[str, Decimal],
    session: AsyncSession,
    cost_config: ShadowCostConfig | None = None,
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
    costs_config = cost_config or ShadowCostConfig()
    open_trades: Sequence[ShadowTrade] = await repo.get_open_trades()
    logger.info(
        "shadow_monitor_check open_trades=%d price_symbols=%s",
        len(open_trades),
        sorted(current_prices.keys()),
    )
    closed = 0
    missing_prices = 0

    for trade in open_trades:
        now = datetime.now(timezone.utc)
        current_price = current_prices.get(trade.symbol)
        if current_price is None:
            missing_prices += 1
            await repo.mark_data_error(trade.id)
            logger.warning(
                "shadow_monitor_missing_price trade_id=%s symbol=%s direction=%s",
                trade.id,
                trade.symbol,
                trade.direction,
            )
            continue

        mark_pnl = (
            (current_price - trade.entry_price) * trade.quantity
            if trade.direction == "LONG"
            else (trade.entry_price - current_price) * trade.quantity
        )
        await repo.update_excursions(
            trade.id,
            favorable_usdt=max(Decimal("0"), mark_pnl),
            adverse_usdt=min(Decimal("0"), mark_pnl),
        )

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

        max_hold = getattr(trade, "max_hold_seconds", None)
        if (
            exit_price is None
            and isinstance(max_hold, int)
            and max_hold > 0
            and (now - trade.opened_at).total_seconds() >= max_hold
        ):
            exit_price, status = current_price, "MAX_HOLD"

        if exit_price is None:
            continue

        duration = (now - trade.opened_at).total_seconds()
        pnl_result = calculate_shadow_pnl(
            direction=trade.direction,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            quantity=trade.quantity,
            margin_usdt=_decimal_cost(getattr(trade, "margin_usdt", 0)),
            opened_at=trade.opened_at,
            closed_at=now,
            config=costs_config,
        )
        pnl = float(pnl_result.gross_pnl_usdt)

        await repo.close_trade(
            trade_id=trade.id,
            exit_price=exit_price,
            pnl_usdt=pnl,
            duration_seconds=duration,
            status=status,
            closed_at=now,
            gross_pnl_usdt=pnl_result.gross_pnl_usdt,
            net_pnl_usdt=pnl_result.net_pnl_usdt,
            exit_reason=status,
            entry_fee_usdt=pnl_result.entry_fee_usdt,
            exit_fee_usdt=pnl_result.exit_fee_usdt,
            funding_fee_usdt=pnl_result.funding_fee_usdt,
            estimated_slippage_usdt=pnl_result.slippage_cost_usdt,
            entry_slippage_usdt=pnl_result.entry_slippage_usdt,
            exit_slippage_usdt=pnl_result.exit_slippage_usdt,
            net_return_on_margin_pct=pnl_result.net_return_on_margin_pct,
            pnl_calculation_status="COST_ADJUSTED",
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
                closed = await check_and_close_shadow_trades(
                    prices,
                    session,
                    ShadowCostConfig(
                        taker_fee_rate=settings.SHADOW_TAKER_FEE_RATE,
                        slippage_bps=settings.SHADOW_SLIPPAGE_BPS,
                        funding_rate_per_interval=settings.SHADOW_FUNDING_RATE_PER_INTERVAL,
                        funding_interval_hours=settings.SHADOW_FUNDING_INTERVAL_HOURS,
                    ),
                )
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
