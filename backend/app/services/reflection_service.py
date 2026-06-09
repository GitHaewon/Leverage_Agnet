"""
Reflection Service — 비즈니스 로직.

아키텍처 규칙: 로직은 Service에만 위치한다.
Repository는 SQL/ORM 쿼리만 담당한다.
"""
from __future__ import annotations

import logging
import math
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reflection_agent import ReflectionResult, run_reflection
from app.core.config import settings
from app.models.reflection_report import ReflectionReport
from app.repositories.reflection_repository import ReflectionRepository
from app.schemas.reflection import (
    ReflectionInput,
    ReflectionReportCreate,
    ReflectionReportResponse,
)

logger = logging.getLogger(__name__)


class ReflectionService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = ReflectionRepository(db)

    # ── 회고 생성 (포지션 종료 시 호출) ──────────────────────────────────────────

    async def run_and_save(self, inp: ReflectionInput) -> ReflectionReport:
        """
        ReflectionAgent를 실행하고 결과를 DB에 저장한다.
        동일 position_id의 리포트가 이미 존재하면 기존 레코드를 반환한다 (멱등).
        """
        existing = await self._repo.get_by_position_id(inp.position_id)
        if existing is not None:
            logger.info(
                "reflection already exists for position=%s, skipping", inp.position_id
            )
            return existing

        logger.info(
            "running ReflectionAgent for position=%s user=%s",
            inp.position_id, inp.user_id,
        )

        result: ReflectionResult = run_reflection(inp)

        if result.error:
            logger.warning(
                "ReflectionAgent error for position=%s: %s", inp.position_id, result.error
            )

        trade_context = _build_trade_context_snapshot(inp)

        data = ReflectionReportCreate(
            position_id=inp.position_id,
            user_id=inp.user_id,
            journal_id=inp.journal_id,
            summary=result.output.summary,
            strengths=result.output.strengths,
            mistakes=result.output.mistakes,
            improvements=result.output.improvements,
            entry_analysis=result.output.entry_analysis or None,
            pnl_cause=result.output.pnl_cause or None,
            risk_rule_violations=result.risk_rule_violations,
            ai_grade=result.output.ai_grade,
            trade_context=trade_context,
            model_used=settings.CLAUDE_MODEL,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )
        return await self._repo.create(data)

    # ── 조회 ─────────────────────────────────────────────────────────────────────

    async def get_by_position(
        self, position_id: uuid.UUID, user_id: uuid.UUID
    ) -> ReflectionReportResponse:
        report = await self._repo.get_by_position_id_and_user(position_id, user_id)
        if report is None:
            raise ReflectionNotFoundError(position_id)
        return ReflectionReportResponse.model_validate(report)

    async def list_reports(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        reports, total = await self._repo.list_by_user(user_id, page, size)
        return {
            "items": [ReflectionReportResponse.model_validate(r) for r in reports],
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total > 0 else 1,
        }


# ── 예외 ─────────────────────────────────────────────────────────────────────

class ReflectionNotFoundError(Exception):
    def __init__(self, position_id: uuid.UUID) -> None:
        super().__init__(f"Reflection not found for position {position_id}")
        self.position_id = position_id


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _build_trade_context_snapshot(inp: ReflectionInput) -> dict[str, Any]:
    """ReflectionInput을 DB 저장용 컨텍스트 스냅샷으로 변환한다."""
    return {
        "coin": inp.coin,
        "symbol": inp.symbol,
        "direction": inp.direction,
        "leverage": inp.leverage,
        "entry_price": str(inp.entry_price),
        "close_price": str(inp.close_price),
        "stop_loss": str(inp.stop_loss),
        "take_profit": str(inp.take_profit) if inp.take_profit else None,
        "net_pnl": str(inp.net_pnl),
        "pnl_percentage": str(inp.pnl_percentage),
        "duration_seconds": inp.duration_seconds,
        "close_reason": inp.close_reason,
        "signal_confidence": inp.signal_confidence,
        "signal_reasons": inp.signal_reasons,
        "signal_rr_ratio": inp.signal_rr_ratio,
    }
