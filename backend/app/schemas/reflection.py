"""
Reflection Pydantic v2 스키마.

모든 API 입출력은 이 스키마를 통과한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── 에이전트 입력 ─────────────────────────────────────────────────────────────

class ReflectionInput(BaseModel):
    """ReflectionAgent에 전달하는 거래 컨텍스트."""
    model_config = ConfigDict(str_strip_whitespace=True)

    position_id: uuid.UUID
    user_id: uuid.UUID
    journal_id: uuid.UUID | None = None

    # 거래 기본 정보
    coin: str = Field(max_length=10)
    symbol: str = Field(max_length=20)
    direction: Literal["LONG", "SHORT"]
    leverage: int = Field(ge=1, le=20)
    entry_price: Decimal
    close_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None = None
    net_pnl: Decimal
    pnl_percentage: Decimal
    duration_seconds: int = Field(ge=0)
    close_reason: str

    # AI 시그널 컨텍스트 (없으면 None)
    signal_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_reasons: list[str] = Field(default_factory=list)
    signal_rr_ratio: float | None = None
    signal_entry_price: Decimal | None = None
    signal_tp: Decimal | None = None
    signal_sl: Decimal | None = None

    # 사용자 설정 컨텍스트 (리스크 규칙 위반 검증용)
    user_max_leverage: int = Field(default=20, ge=1, le=20)

    # 가격 액션 요약 (선택)
    price_action_summary: str | None = None


# ── 에이전트 출력 (Claude 원본) ───────────────────────────────────────────────

class ReflectionOutput(BaseModel):
    """Claude Sonnet이 생성하는 구조화된 회고 출력."""

    # 사용자 지정 4-field spec
    summary: str = Field(description="1-2문장 거래 요약")
    strengths: list[str] = Field(description="잘한 점 (2-4가지)")
    mistakes: list[str] = Field(description="실수 또는 개선이 필요한 점 (2-4가지)")
    improvements: list[str] = Field(description="다음 번 실천 사항 (2-4가지)")

    # 심층 분석 (DB 저장 + 응답 포함)
    entry_analysis: str = Field(description="진입 시점 평가")
    pnl_cause: str = Field(description="수익/손실 근본 원인")
    ai_grade: Literal["A", "B", "C", "D"] = Field(description="거래 품질 등급")


# ── 생성 스키마 ───────────────────────────────────────────────────────────────

class ReflectionReportCreate(BaseModel):
    """서비스 레이어에서 DB 저장 시 사용."""
    position_id: uuid.UUID
    user_id: uuid.UUID
    journal_id: uuid.UUID | None = None

    summary: str
    strengths: list[str]
    mistakes: list[str]
    improvements: list[str]

    entry_analysis: str | None = None
    pnl_cause: str | None = None
    risk_rule_violations: list[str] = Field(default_factory=list)
    ai_grade: Literal["A", "B", "C", "D"] = "C"

    trade_context: dict[str, Any] | None = None
    model_used: str
    tokens_input: int | None = None
    tokens_output: int | None = None


# ── 응답 스키마 ───────────────────────────────────────────────────────────────

class ReflectionReportResponse(BaseModel):
    """GET /reflections/{position_id} 응답."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position_id: uuid.UUID
    user_id: uuid.UUID
    journal_id: uuid.UUID | None

    # 핵심 4-field
    summary: str
    strengths: list[str]
    mistakes: list[str]
    improvements: list[str]

    # 심층 분석
    entry_analysis: str | None
    pnl_cause: str | None
    risk_rule_violations: list[str]
    ai_grade: str

    # 메타
    trade_context: dict[str, Any] | None
    model_used: str
    tokens_input: int | None
    tokens_output: int | None

    created_at: datetime
    updated_at: datetime


class ReflectionTriggerRequest(BaseModel):
    """POST /reflections/{position_id}/trigger 요청."""
    journal_id: uuid.UUID | None = None
    price_action_summary: str | None = Field(default=None, max_length=2000)
