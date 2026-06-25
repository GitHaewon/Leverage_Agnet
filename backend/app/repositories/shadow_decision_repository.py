"""Shadow Decision DB 쿼리."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shadow_decision import ShadowDecision
from app.schemas.shadow_decisions import ShadowDecisionRecord, ShadowDecisionStats


class ShadowDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: ShadowDecisionRecord) -> None:
        """파이프라인 사이클 결정을 DB에 기록한다."""
        orm = ShadowDecision(
            run_id=record.run_id,
            user_id=record.user_id,
            coin=record.coin,
            decided_at=record.decided_at,
            market_regime=record.market_regime,
            chart_score=Decimal(str(record.chart_score)) if record.chart_score is not None else None,
            strategy_type=record.strategy_type,
            candidate_action=record.candidate_action,
            expected_entry=record.expected_entry,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            candidate_rr=Decimal(str(record.candidate_rr)) if record.candidate_rr is not None else None,
            candidate_leverage=record.candidate_leverage,
            ai_decision=record.ai_decision,
            ai_confidence=Decimal(str(record.ai_confidence)) if record.ai_confidence is not None else None,
            ai_critical_contradiction=record.ai_critical_contradiction,
            risk_passed=record.risk_passed,
            risk_reject_reason=record.risk_reject_reason,
            final_action=record.final_action,
            rejection_stage=record.rejection_stage,
            rejection_reason=(record.rejection_reason or "")[:200] if record.rejection_reason else None,
            shadow_trade_id=record.shadow_trade_id,
        )
        self._session.add(orm)
        await self._session.flush()

    async def list_decisions(
        self,
        user_id: str,
        *,
        coin: str | None = None,
        final_action: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ShadowDecision], int]:
        stmt = select(ShadowDecision).where(ShadowDecision.user_id == user_id)
        if coin:
            stmt = stmt.where(ShadowDecision.coin == coin)
        if final_action:
            stmt = stmt.where(ShadowDecision.final_action == final_action)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ShadowDecision.decided_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self, user_id: str) -> ShadowDecisionStats:
        stmt = select(ShadowDecision).where(ShadowDecision.user_id == user_id)
        rows = (await self._session.execute(stmt)).scalars().all()

        total = len(rows)
        executed = sum(1 for r in rows if r.final_action in ("LONG", "SHORT"))
        held = total - executed
        hold_rate = (held / total * 100.0) if total > 0 else 0.0

        rejected_at_decision = sum(1 for r in rows if r.rejection_stage == "DECISION_ENGINE")
        rejected_at_ai       = sum(1 for r in rows if r.rejection_stage == "AI_REVIEW")
        rejected_at_risk     = sum(1 for r in rows if r.rejection_stage == "RISK_ENGINE")
        rejected_at_position = sum(1 for r in rows if r.rejection_stage == "POSITION_LIMIT")

        ai_reviewed = [r for r in rows if r.ai_confidence is not None]
        avg_ai_confidence = (
            float(sum(r.ai_confidence for r in ai_reviewed) / len(ai_reviewed))
            if ai_reviewed else None
        )
        ai_approved = sum(1 for r in ai_reviewed if r.ai_decision == "APPROVE")
        ai_approve_rate = (
            ai_approved / len(ai_reviewed) * 100.0 if ai_reviewed else None
        )

        return ShadowDecisionStats(
            total_cycles=total,
            executed=executed,
            held=held,
            hold_rate=round(hold_rate, 1),
            rejected_at_decision=rejected_at_decision,
            rejected_at_ai=rejected_at_ai,
            rejected_at_risk=rejected_at_risk,
            rejected_at_position=rejected_at_position,
            avg_ai_confidence=round(avg_ai_confidence, 4) if avg_ai_confidence is not None else None,
            ai_approve_rate=round(ai_approve_rate, 1) if ai_approve_rate is not None else None,
        )
