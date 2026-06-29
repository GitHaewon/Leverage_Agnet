"""Shadow Trade DB 쿼리."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shadow.models import ShadowTradeRecord
from agents.risk.models import OpenPosition
from app.models.shadow_trade import ShadowTrade
from app.schemas.shadow_trades import ShadowTradeStats
from agents.shadow.risk_state import (
    ClosedShadowPnl,
    ShadowLossState,
    UnresolvedOpenRiskError,
    rebuild_loss_state,
)


class ShadowTradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: ShadowTradeRecord) -> bool:
        """ShadowTradeRecord를 DB에 저장한다."""
        if not record.signal_id:
            raise ValueError("signal_id is required for idempotent Shadow persistence")
        strategy_version = record.strategy_version or "legacy_unknown"
        orm = ShadowTrade(
            id=uuid.UUID(record.id),
            user_id=record.user_id,
            coin=record.coin,
            symbol=record.symbol,
            direction=record.direction,
            entry_price=record.entry_price,
            tp_price=record.tp_price,
            sl_price=record.sl_price,
            quantity=record.quantity,
            leverage=record.leverage,
            status=record.status,
            opened_at=record.opened_at,
            strategy_version=strategy_version,
            experiment_label=record.experiment_label,
            signal_id=record.signal_id,
            position_size_usdt=record.position_size_usdt,
            margin_usdt=record.margin_usdt,
            tp_distance=record.tp_distance,
            sl_distance=record.sl_distance,
            expected_max_loss_usdt=record.expected_max_loss_usdt,
            actual_max_loss_usdt=record.actual_max_loss_usdt,
            risk_budget_usdt=record.risk_budget_usdt,
            risk_budget_utilization=record.risk_budget_utilization,
            leverage_reason=record.leverage_reason,
            reviewer_input_summary=record.reviewer_input_summary,
            reviewer_result=record.reviewer_result,
            reviewer_score=record.reviewer_score,
            market_regime=record.market_regime,
            entry_fee_usdt=record.entry_fee_usdt,
            exit_fee_usdt=record.exit_fee_usdt,
            entry_slippage_usdt=record.entry_slippage_usdt,
            exit_slippage_usdt=record.exit_slippage_usdt,
            funding_fee_usdt=record.funding_fee_usdt,
            estimated_slippage_usdt=record.estimated_slippage_usdt,
            mfe_usdt=record.mfe_usdt,
            mae_usdt=record.mae_usdt,
            data_error=record.data_error,
            system_error=record.system_error,
            max_hold_seconds=record.max_hold_seconds,
            rejection_code=record.rejection_code,
            rejection_reason=record.rejection_reason,
            exit_price=record.exit_price,
            pnl_usdt=record.pnl_usdt,
            duration_seconds=record.duration_seconds,
            closed_at=record.closed_at,
            exit_reason=record.exit_reason,
            gross_pnl_usdt=record.gross_pnl_usdt,
            net_pnl_usdt=record.net_pnl_usdt,
            net_return_on_margin_pct=record.net_return_on_margin_pct,
            pnl_calculation_status=record.pnl_calculation_status,
        )
        values = {
            key: value
            for key, value in orm.__dict__.items()
            if key != "_sa_instance_state"
        }
        stmt = (
            pg_insert(ShadowTrade)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["signal_id", "strategy_version"]
            )
            .returning(ShadowTrade.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_open_trades(self, user_id: str | None = None) -> Sequence[ShadowTrade]:
        """OPEN 상태 거래 조회. user_id 지정 시 해당 사용자만 반환."""
        stmt = select(ShadowTrade).where(ShadowTrade.status == "OPEN")
        if user_id is not None:
            stmt = stmt.where(ShadowTrade.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_open_risk_usdt(
        self, user_id: str, strategy_version: str | None = None
    ) -> Decimal:
        stmt = select(ShadowTrade).where(
            ShadowTrade.user_id == user_id,
            ShadowTrade.status == "OPEN",
        )
        if strategy_version is not None:
            stmt = stmt.where(ShadowTrade.strategy_version == strategy_version)
        trades = (await self._session.execute(stmt)).scalars().all()
        unresolved = [
            str(trade.id)
            for trade in trades
            if trade.actual_max_loss_usdt is None
            or trade.actual_max_loss_usdt <= 0
        ]
        if unresolved:
            raise UnresolvedOpenRiskError(
                "OPEN_RISK_UNRESOLVED: " + ",".join(unresolved)
            )
        return sum(
            (trade.actual_max_loss_usdt for trade in trades),
            Decimal("0"),
        )

    async def get_loss_state(
        self, user_id: str, strategy_version: str
    ) -> ShadowLossState:
        stmt = (
            select(ShadowTrade)
            .where(
                ShadowTrade.user_id == user_id,
                ShadowTrade.strategy_version == strategy_version,
                ShadowTrade.status.in_(("TP_HIT", "SL_HIT", "MAX_HOLD")),
                ShadowTrade.closed_at.is_not(None),
            )
            .order_by(ShadowTrade.closed_at.asc())
        )
        trades = (await self._session.execute(stmt)).scalars().all()
        return rebuild_loss_state(
            ClosedShadowPnl(
                closed_at=trade.closed_at,
                net_pnl_usdt=trade.net_pnl_usdt,
                gross_pnl_usdt=(
                    trade.gross_pnl_usdt
                    if trade.pnl_calculation_status == "GROSS_FALLBACK"
                    and trade.gross_pnl_usdt is not None
                    else (
                        Decimal(str(trade.pnl_usdt))
                        if trade.pnl_calculation_status == "GROSS_FALLBACK"
                        and trade.pnl_usdt is not None
                        else None
                    )
                ),
            )
            for trade in trades
        )

    async def get_open_positions_for_risk(self, user_id: str) -> list[OpenPosition]:
        """Aggregate OPEN shadow fills into position-shaped risk inputs."""
        stmt = select(ShadowTrade).where(
            ShadowTrade.user_id == user_id,
            ShadowTrade.status == "OPEN",
        )
        trades = (await self._session.execute(stmt)).scalars().all()
        unresolved = [
            str(trade.id)
            for trade in trades
            if trade.actual_max_loss_usdt is None
            or trade.actual_max_loss_usdt <= 0
        ]
        if unresolved:
            raise UnresolvedOpenRiskError(
                "OPEN_RISK_UNRESOLVED: " + ",".join(unresolved)
            )
        grouped: dict[tuple[str, str], list[ShadowTrade]] = {}
        for trade in trades:
            grouped.setdefault((trade.coin, trade.direction), []).append(trade)

        positions: list[OpenPosition] = []
        for legs in grouped.values():
            total_qty = sum((leg.quantity for leg in legs), Decimal("0"))
            if total_qty <= 0:
                continue
            entry = sum((leg.entry_price * leg.quantity for leg in legs), Decimal("0")) / total_qty
            stop_loss = sum((leg.sl_price * leg.quantity for leg in legs), Decimal("0")) / total_qty
            leverage = round(
                sum((Decimal(leg.leverage) * leg.quantity for leg in legs), Decimal("0")) / total_qty
            )
            original = min(legs, key=lambda leg: leg.opened_at)
            original_risk = sum(
                (leg.actual_max_loss_usdt for leg in legs),
                Decimal("0"),
            )
            positions.append(
                OpenPosition(
                    id=original.id,
                    coin=original.coin,
                    symbol=original.symbol,
                    direction=original.direction,
                    entry_price=entry,
                    quantity=total_qty,
                    stop_loss=stop_loss,
                    leverage=int(leverage),
                    dca_count=max(0, len(legs) - 1),
                    original_risk_usdt=original_risk,
                )
            )
        return positions

    async def list_trades(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ShadowTrade], int]:
        """사용자의 shadow trades 목록과 총 개수를 반환한다."""
        stmt = select(ShadowTrade).where(ShadowTrade.user_id == user_id)
        if status:
            stmt = stmt.where(ShadowTrade.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ShadowTrade.opened_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self, user_id: str) -> ShadowTradeStats:
        """사용자의 shadow trading 집계 통계를 반환한다."""
        stmt = select(ShadowTrade).where(ShadowTrade.user_id == user_id)
        all_trades = (await self._session.execute(stmt)).scalars().all()

        total = sum(1 for t in all_trades if t.status != "REJECTED")
        open_trades = sum(1 for t in all_trades if t.status == "OPEN")
        tp_hit = sum(1 for t in all_trades if t.status == "TP_HIT")
        sl_hit = sum(1 for t in all_trades if t.status == "SL_HIT")
        max_hold = sum(1 for t in all_trades if t.status == "MAX_HOLD")
        closed = tp_hit + sl_hit + max_hold

        closed_pnls: list[float] = []
        for trade in all_trades:
            if trade.status not in {"TP_HIT", "SL_HIT", "MAX_HOLD"}:
                continue
            if (
                trade.pnl_calculation_status == "COST_ADJUSTED"
                and trade.net_pnl_usdt is not None
            ):
                closed_pnls.append(float(trade.net_pnl_usdt))
            elif trade.pnl_calculation_status == "GROSS_FALLBACK":
                fallback = (
                    trade.gross_pnl_usdt
                    if trade.gross_pnl_usdt is not None
                    else trade.pnl_usdt
                )
                if fallback is not None:
                    closed_pnls.append(float(fallback))
        total_pnl = sum(closed_pnls) if closed_pnls else 0.0
        avg_pnl = total_pnl / len(closed_pnls) if closed_pnls else 0.0
        best_pnl = max(closed_pnls) if closed_pnls else None
        worst_pnl = min(closed_pnls) if closed_pnls else None

        durations = [t.duration_seconds for t in all_trades if t.duration_seconds is not None]
        avg_duration_min = (sum(durations) / len(durations) / 60.0) if durations else None

        wins = sum(1 for pnl in closed_pnls if pnl > 0)
        win_rate = (wins / closed * 100.0) if closed > 0 else 0.0

        return ShadowTradeStats(
            total_trades=total,
            open_trades=open_trades,
            closed_trades=closed,
            tp_hit=tp_hit,
            sl_hit=sl_hit,
            win_rate=round(win_rate, 1),
            total_pnl_usdt=round(total_pnl, 2),
            avg_pnl_usdt=round(avg_pnl, 2),
            best_pnl_usdt=round(best_pnl, 2) if best_pnl is not None else None,
            worst_pnl_usdt=round(worst_pnl, 2) if worst_pnl is not None else None,
            avg_duration_minutes=round(avg_duration_min, 1) if avg_duration_min is not None else None,
        )

    async def close_trade(
        self,
        trade_id: uuid.UUID,
        *,
        exit_price: Decimal,
        pnl_usdt: float,
        duration_seconds: float,
        status: str,
        closed_at: datetime,
        gross_pnl_usdt: Decimal | None = None,
        net_pnl_usdt: Decimal | None = None,
        exit_reason: str | None = None,
        entry_fee_usdt: Decimal | None = None,
        exit_fee_usdt: Decimal | None = None,
        funding_fee_usdt: Decimal | None = None,
        estimated_slippage_usdt: Decimal | None = None,
        entry_slippage_usdt: Decimal | None = None,
        exit_slippage_usdt: Decimal | None = None,
        net_return_on_margin_pct: Decimal | None = None,
        pnl_calculation_status: str = "COST_ADJUSTED",
    ) -> None:
        """TP/SL 체결 확인 후 청산 데이터를 원자적으로 업데이트한다.

        status == "OPEN" 조건을 포함하므로 중복 청산이 발생하지 않는다.
        """
        stmt = (
            update(ShadowTrade)
            .where(ShadowTrade.id == trade_id, ShadowTrade.status == "OPEN")
            .values(
                exit_price=exit_price,
                pnl_usdt=pnl_usdt,
                duration_seconds=duration_seconds,
                status=status,
                closed_at=closed_at,
                gross_pnl_usdt=gross_pnl_usdt,
                net_pnl_usdt=net_pnl_usdt,
                exit_reason=exit_reason or status,
                entry_fee_usdt=entry_fee_usdt,
                exit_fee_usdt=exit_fee_usdt,
                funding_fee_usdt=funding_fee_usdt,
                estimated_slippage_usdt=estimated_slippage_usdt,
                entry_slippage_usdt=entry_slippage_usdt,
                exit_slippage_usdt=exit_slippage_usdt,
                net_return_on_margin_pct=net_return_on_margin_pct,
                pnl_calculation_status=pnl_calculation_status,
            )
        )
        await self._session.execute(stmt)

    async def update_excursions(
        self, trade_id: uuid.UUID, *, favorable_usdt: Decimal, adverse_usdt: Decimal
    ) -> None:
        """Track best favorable and worst adverse mark-to-market observations."""
        stmt = (
            update(ShadowTrade)
            .where(ShadowTrade.id == trade_id, ShadowTrade.status == "OPEN")
            .values(
                mfe_usdt=func.greatest(ShadowTrade.mfe_usdt, favorable_usdt),
                mae_usdt=func.least(ShadowTrade.mae_usdt, adverse_usdt),
            )
        )
        await self._session.execute(stmt)

    async def mark_data_error(self, trade_id: uuid.UUID) -> None:
        await self._session.execute(
            update(ShadowTrade)
            .where(ShadowTrade.id == trade_id, ShadowTrade.status == "OPEN")
            .values(data_error=True)
        )
