"""
AI Trading Coach 스키마.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field


# ── 에이전트 입력 전용 TypedDict ──────────────────────────────────────────────

class JournalData(TypedDict):
    """TradeJournal ORM → 에이전트 입력 직렬화 형식."""
    coin: str
    direction: str
    net_pnl: float
    entry_time: datetime       # UTC tzinfo 포함
    duration_seconds: int
    close_reason: str
    strategy: str | None
    leverage: int
    pnl_percentage: float


# ── 분석 결과 단위 ────────────────────────────────────────────────────────────

class HourStat(BaseModel):
    hour: int                  # 0-23 (KST 기준)
    label: str                 # "새벽(00-05시)" 등
    count: int
    win_rate: float
    avg_pnl: float
    deviation: float           # 전체 평균 승률 대비 편차


class WeekdayStat(BaseModel):
    weekday: int               # 0=월 … 6=일
    name: str                  # "월", "화" …
    count: int
    win_rate: float
    avg_pnl: float
    deviation: float


class CoinStat(BaseModel):
    coin: str
    count: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    deviation: float


class StrategyStat(BaseModel):
    strategy: str
    count: int
    win_rate: float
    avg_pnl: float
    deviation: float


class RepeatedMistake(BaseModel):
    text: str
    count: int


class EmotionalPattern(BaseModel):
    pattern_type: str          # "revenge_trading", "night_trading_poor_performance" 등
    severity: str              # "high" | "medium" | "low"
    evidence: str              # 구체적 수치 포함 설명
    occurrences: int


# ── Service → Repository ─────────────────────────────────────────────────────

class CoachingReportCreate(BaseModel):
    user_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    overall_stats: dict
    hourly_stats: list[dict]
    weekday_stats: list[dict]
    coin_stats: list[dict]
    strategy_stats: list[dict]
    repeated_mistakes: list[dict]
    emotional_patterns: list[dict]
    risk_behavior_score: int
    coach_summary: str
    strengths: list[str]
    blind_spots: list[str]
    weekly_goal: str
    skip_reason: str | None
    model_used: str
    tokens_input: int
    tokens_output: int


# ── API 응답 ──────────────────────────────────────────────────────────────────

class CoachingReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    overall_stats: dict
    hourly_stats: list[dict]
    weekday_stats: list[dict]
    coin_stats: list[dict]
    strategy_stats: list[dict]
    repeated_mistakes: list[dict]
    emotional_patterns: list[dict]
    risk_behavior_score: int
    coach_summary: str
    strengths: list[str]
    blind_spots: list[str]
    weekly_goal: str
    skip_reason: str | None
    model_used: str
    tokens_input: int
    tokens_output: int
    created_at: datetime


# ── API 요청 ──────────────────────────────────────────────────────────────────

class CoachingTriggerRequest(BaseModel):
    period_days: int = Field(default=28, ge=7, le=90)
