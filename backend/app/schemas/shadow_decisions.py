"""Shadow Decision 스키마 — 도메인 레코드(저장용) + Pydantic 출력 스키마."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel


def pipeline_status_to_action(
    status: Any,
    execution_result: Any = None,
) -> Literal["LONG", "SHORT", "HOLD"]:
    """PipelineResult → final_action.

    체결된 경우 execution_result.entry_order.side (BUY=LONG / SELL=SHORT)로 방향을 판단한다.
    인식 불가 값은 HOLD로 처리한다.
    """
    # 체결된 경우 entry_order.side에서 방향 추출
    if execution_result is not None:
        entry_order = getattr(execution_result, "entry_order", None)
        side = getattr(entry_order, "side", None)
        if side == "BUY":
            return "LONG"
        if side == "SELL":
            return "SHORT"
    # PipelineStatus enum 또는 문자열 fallback
    s = str(status or "").upper()
    if "LONG" in s:
        return "LONG"
    if "SHORT" in s:
        return "SHORT"
    return "HOLD"


def infer_rejection_stage(
    status: Any,
    rejection_reason: str | None,
) -> str | None:
    """PipelineStatus + rejection_reason에서 거부 단계를 추론한다."""
    s = str(status or "").upper()
    if "COMPLETED" in s:
        return None  # 체결됨
    if "REJECTED" in s:
        return "POSITION_LIMIT"
    if rejection_reason:
        r = rejection_reason.lower()
        if "ai" in r or "review" in r or "reviewer" in r:
            return "AI_REVIEW"
        if "risk" in r:
            return "RISK_ENGINE"
        if "portfolio" in r or "포트폴리오" in rejection_reason:
            return "POSITION_LIMIT"
        if "position" in r:
            return "POSITION_LIMIT"
    return "DECISION_ENGINE"  # HOLD 기본값


# ── 도메인 레코드 (저장 DTO) ──────────────────────────────────────────────────────
# analysis_worker가 파이프라인 결과를 담아 repository.save()에 전달한다.
# 진단 필드는 파이프라인 계측 완료 전까지 None 허용.

@dataclass
class ShadowDecisionRecord:
    run_id:      str
    user_id:     str
    coin:        str
    final_action: Literal["LONG", "SHORT", "HOLD"]

    decided_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # DecisionEngine
    market_regime:  str | None = None
    chart_score:    float | None = None
    strategy_type:  str | None = None

    # TradeCandidate
    candidate_action:   str | None = None
    expected_entry:     Decimal | None = None
    stop_loss:          Decimal | None = None
    take_profit:        Decimal | None = None
    candidate_rr:       float | None = None
    candidate_leverage: int | None = None

    # ReviewerAgent
    ai_decision:               str | None = None   # APPROVE | REJECT | ERROR | SKIPPED
    ai_confidence:             float | None = None
    ai_critical_contradiction: bool | None = None

    # RiskEngine
    risk_passed:        bool | None = None
    risk_reject_reason: str | None = None

    # 거부 맥락
    rejection_stage:  str | None = None   # DECISION_ENGINE | AI_REVIEW | RISK_ENGINE | POSITION_LIMIT
    rejection_reason: str | None = None

    # 체결된 경우 shadow_trades FK
    shadow_trade_id: uuid.UUID | None = None


# ── Pydantic 출력 스키마 ──────────────────────────────────────────────────────────

class ShadowDecisionOut(BaseModel):
    id:           uuid.UUID
    run_id:       str
    coin:         str
    decided_at:   datetime

    market_regime:  str | None
    chart_score:    float | None
    strategy_type:  str | None

    candidate_action:   str | None
    expected_entry:     Decimal | None
    stop_loss:          Decimal | None
    take_profit:        Decimal | None
    candidate_rr:       float | None
    candidate_leverage: int | None

    ai_decision:               str | None
    ai_confidence:             float | None
    ai_critical_contradiction: bool | None

    risk_passed:        bool | None
    risk_reject_reason: str | None

    final_action:     str
    rejection_stage:  str | None
    rejection_reason: str | None
    shadow_trade_id:  uuid.UUID | None

    created_at: datetime

    model_config = {"from_attributes": True}


class ShadowDecisionStats(BaseModel):
    total_cycles:        int
    executed:            int    # final_action in (LONG, SHORT)
    held:                int    # final_action == HOLD
    hold_rate:           float  # 0.0 ~ 100.0

    # 거부 단계별 분포 (held 케이스)
    rejected_at_decision: int
    rejected_at_ai:       int
    rejected_at_risk:     int
    rejected_at_position: int

    # AI 리뷰 통계 (executed + rejected_at_risk 합산)
    avg_ai_confidence:   float | None
    ai_approve_rate:     float | None   # 0.0 ~ 100.0
