"""Shadow Decision DB 쿼리."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator.models import AgentResult, PipelineResult
from app.models.shadow_decision import ShadowDecision
from app.schemas.shadow_decisions import ShadowDecisionRecord, ShadowDecisionStats

logger = logging.getLogger(__name__)


class ShadowDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_step(self, run_id: str, step: AgentResult) -> None:
        """OrchestratorLogger storage 호환용 no-op."""
        return None

    async def save_pipeline(self, result: PipelineResult) -> None:
        """OrchestratorLogger storage 호환용 no-op."""
        return None

    async def save_decision_log(self, run_id: str, payload: dict[str, Any]) -> None:
        """Orchestrator decision_log payload를 shadow_decisions row로 저장한다.

        저장 실패는 OrchestratorLogger에서 잡아 파이프라인 실패로 전파하지 않는다.
        이 메서드는 logger storage 프로토콜에 맞춘 DB 어댑터다.
        """
        record = self._record_from_payload(run_id, payload)
        await self.save(record)

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
            long_score=_decimal_from_float(record.long_score),
            short_score=_decimal_from_float(record.short_score),
            risk_score=_decimal_from_float(record.risk_score),
            min_long_score=_decimal_from_float(record.min_long_score),
            min_short_score=_decimal_from_float(record.min_short_score),
            max_risk_score=_decimal_from_float(record.max_risk_score),
            decision_score_summary=(
                (record.decision_score_summary or "")[:500]
                if record.decision_score_summary
                else None
            ),
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

    def _record_from_payload(
        self,
        run_id: str,
        payload: dict[str, Any],
    ) -> ShadowDecisionRecord:
        ai_review = payload.get("ai_review") if isinstance(payload.get("ai_review"), dict) else {}
        risk_result = payload.get("risk_result") if isinstance(payload.get("risk_result"), dict) else {}
        actual_result = (
            payload.get("actual_result")
            if isinstance(payload.get("actual_result"), dict)
            else {}
        )

        decided_at = _parse_datetime(payload.get("timestamp"))
        final_action = _final_action_from_payload(payload)
        rejection_stage = payload.get("rejection_stage")
        if rejection_stage is not None:
            rejection_stage = str(rejection_stage)

        return ShadowDecisionRecord(
            run_id=str(payload.get("run_id") or run_id),
            user_id=str(payload.get("user_id") or ""),
            coin=str(payload.get("coin") or ""),
            final_action=final_action,  # type: ignore[arg-type]
            decided_at=decided_at,
            market_regime=_str_or_none(payload.get("market_regime")),
            chart_score=_chart_score_value(payload.get("chart_score")),
            strategy_type=_str_or_none(payload.get("strategy_type")),
            long_score=_float_or_none(payload.get("long_score")),
            short_score=_float_or_none(payload.get("short_score")),
            risk_score=_float_or_none(payload.get("risk_score")),
            min_long_score=_float_or_none(payload.get("min_long_score")),
            min_short_score=_float_or_none(payload.get("min_short_score")),
            max_risk_score=_float_or_none(payload.get("max_risk_score")),
            decision_score_summary=_str_or_none(payload.get("decision_score_summary")),
            candidate_action=_str_or_none(payload.get("candidate_action")),
            expected_entry=_decimal_or_none(payload.get("expected_entry_price")),
            stop_loss=_decimal_or_none(payload.get("stop_loss")),
            take_profit=_decimal_or_none(payload.get("take_profit")),
            candidate_rr=_float_or_none(payload.get("actual_rr")),
            candidate_leverage=_int_or_none(payload.get("leverage")),
            ai_decision=_str_or_none(ai_review.get("review_action")),
            ai_confidence=_float_or_none(ai_review.get("confidence")),
            ai_critical_contradiction=_bool_or_none(
                ai_review.get("critical_contradiction")
            ),
            risk_passed=_bool_or_none(risk_result.get("approved")),
            risk_reject_reason=_risk_reject_reason(payload, risk_result),
            rejection_stage=rejection_stage,
            rejection_reason=_str_or_none(payload.get("rejection_reason")),
            shadow_trade_id=_shadow_trade_id(actual_result),
        )

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

        rejected_at_decision = sum(
            1 for r in rows
            if _stage_key(r.rejection_stage) in {"decision", "decision_engine"}
        )
        rejected_at_ai = sum(
            1 for r in rows
            if _stage_key(r.rejection_stage) in {"ai_review"}
        )
        rejected_at_risk = sum(
            1 for r in rows
            if _stage_key(r.rejection_stage) in {"risk", "risk_engine"}
        )
        rejected_at_position = sum(
            1 for r in rows
            if _stage_key(r.rejection_stage)
            in {"portfolio", "position_manager", "position_limit"}
        )

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


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.debug("invalid shadow decision timestamp: %s", value)
    return datetime.now(timezone.utc)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _decimal_from_float(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.lower()
        if lower in {"true", "1", "yes"}:
            return True
        if lower in {"false", "0", "no"}:
            return False
    return bool(value)


def _chart_score_value(value: Any) -> float | None:
    if isinstance(value, dict):
        long_score = _float_or_none(value.get("long_score"))
        short_score = _float_or_none(value.get("short_score"))
        if long_score is not None and short_score is not None:
            edge = (long_score - short_score) / 100.0
            return max(-1.0, min(1.0, edge))
        for key in ("score", "value", "technical_score"):
            parsed = _float_or_none(value.get(key))
            if parsed is not None:
                return parsed
        return None
    return _float_or_none(value)


def _final_action_from_payload(payload: dict[str, Any]) -> str:
    action = _str_or_none(payload.get("final_action")) or "HOLD"
    if action in {"LONG", "SHORT"}:
        return action
    return "HOLD"


def _risk_reject_reason(
    payload: dict[str, Any],
    risk_result: dict[str, Any],
) -> str | None:
    for key in ("rejection_reason", "reason"):
        value = risk_result.get(key)
        if value:
            return str(value)
    if payload.get("rejection_stage") == "risk":
        return _str_or_none(payload.get("rejection_reason"))
    return None


def _shadow_trade_id(actual_result: dict[str, Any]) -> uuid.UUID | None:
    order_id = actual_result.get("entry_exchange_order_id")
    if not isinstance(order_id, str):
        return None
    prefix = "shadow-entry-"
    if not order_id.startswith(prefix):
        return None
    try:
        return uuid.UUID(order_id.removeprefix(prefix))
    except ValueError:
        return None


def _stage_key(value: Any) -> str:
    return str(value or "").strip().lower()
