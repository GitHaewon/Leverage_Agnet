"""
Memory Layer — Qdrant 저장 문서 빌더.

각 소스 타입(Journal, Reflection, Strategy)을:
  1. 임베딩용 자연어 텍스트 (embed_text)
  2. 필터링 + 반환용 페이로드 (payload)
  3. 중복 방지 Point ID (point_id)

로 변환한다.

point_id는 position_id를 사용한다.
세 컬렉션이 별도이므로 동일한 UUID를 각 컬렉션에서 독립적으로 사용 가능하다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.models.trade_journal import TradeJournal
from app.models.reflection_report import ReflectionReport


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _to_ts(dt: datetime | None) -> int | None:
    """datetime → Unix timestamp (정수). 필터링 범위 조건에 사용."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _pct_str(val: Decimal | None) -> str:
    if val is None:
        return "0%"
    sign = "+" if val >= 0 else ""
    return f"{sign}{float(val):.2f}%"


def _duration_label(seconds: int) -> str:
    if seconds < 3600:
        return f"{seconds // 60}분"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"


# ── Journal 문서 ──────────────────────────────────────────────────────────────

@dataclass
class JournalDocument:
    """
    trade_journals 컬렉션 문서.
    trade_journal.ai_decision 내의 시그널 근거와 진입·청산 이유를
    자연어 텍스트로 구성하여 시맨틱 유사 거래 검색에 활용한다.
    """
    point_id: str
    embed_text: str
    payload: dict[str, Any]

    @classmethod
    def from_orm(cls, journal: TradeJournal) -> "JournalDocument":
        is_win = float(journal.net_pnl) > 0

        # 임베딩 텍스트: 거래의 핵심 맥락을 자연어로 표현
        parts = [
            f"{journal.coin} {journal.direction} | {journal.close_reason}",
            f"레버리지 {journal.leverage}x | 보유 {_duration_label(journal.duration_seconds)}",
            f"P&L {_pct_str(journal.pnl_percentage)}",
        ]

        if journal.strategy:
            parts.append(f"전략: {journal.strategy}")

        if journal.entry_reason:
            parts.append(f"진입 근거: {journal.entry_reason}")

        if journal.exit_reason:
            parts.append(f"청산 사유: {journal.exit_reason}")

        # AI 시그널 근거
        ai = journal.ai_decision or {}
        reasons: list[str] = ai.get("reasons") or []
        if reasons:
            parts.append("AI 근거: " + " | ".join(reasons[:3]))

        tech = ai.get("technical_score")
        if tech is not None:
            parts.append(f"기술점수: {float(tech):+.2f}")

        return cls(
            point_id=str(journal.position_id),
            embed_text="\n".join(parts),
            payload={
                "source": "journal",
                "user_id": str(journal.user_id),
                "position_id": str(journal.position_id),
                "journal_id": str(journal.id),
                "coin": journal.coin,
                "symbol": journal.symbol,
                "direction": journal.direction,
                "leverage": journal.leverage,
                "is_ai_trade": journal.is_ai_trade,
                "net_pnl": float(journal.net_pnl),
                "pnl_percentage": float(journal.pnl_percentage),
                "close_reason": journal.close_reason,
                "duration_seconds": journal.duration_seconds,
                "is_win": is_win,
                "strategy": journal.strategy,
                "entry_time_ts": _to_ts(journal.entry_time),
                "exit_time_ts": _to_ts(journal.exit_time),
            },
        )


# ── Reflection 문서 ───────────────────────────────────────────────────────────

@dataclass
class ReflectionDocument:
    """
    trade_reflections 컬렉션 문서.
    AI 코칭 내용(강점, 실수, 개선, 진입 분석)을 임베딩하여
    비슷한 패턴의 회고를 검색하는 데 활용한다.
    """
    point_id: str
    embed_text: str
    payload: dict[str, Any]

    @classmethod
    def from_orm(cls, report: ReflectionReport) -> "ReflectionDocument":
        ctx = report.trade_context or {}
        is_win = float(ctx.get("net_pnl", 0)) > 0 if ctx else False

        parts = [
            f"[{report.ai_grade}등급] {report.summary}",
        ]

        strengths: list[str] = report.strengths or []
        if strengths:
            parts.append("강점: " + " | ".join(strengths))

        mistakes: list[str] = report.mistakes or []
        if mistakes:
            parts.append("실수: " + " | ".join(mistakes))

        improvements: list[str] = report.improvements or []
        if improvements:
            parts.append("개선: " + " | ".join(improvements))

        if report.entry_analysis:
            parts.append(f"진입 분석: {report.entry_analysis}")

        if report.pnl_cause:
            parts.append(f"손익 원인: {report.pnl_cause}")

        violations: list[str] = report.risk_rule_violations or []
        if violations:
            parts.append("리스크 위반: " + " | ".join(violations))

        return cls(
            point_id=str(report.position_id),
            embed_text="\n".join(parts),
            payload={
                "source": "reflection",
                "user_id": str(report.user_id),
                "position_id": str(report.position_id),
                "report_id": str(report.id),
                "journal_id": str(report.journal_id) if report.journal_id else None,
                "coin": ctx.get("coin", ""),
                "direction": ctx.get("direction", ""),
                "leverage": ctx.get("leverage"),
                "net_pnl": float(ctx.get("net_pnl", 0)) if ctx else 0.0,
                "is_win": is_win,
                "ai_grade": report.ai_grade,
                "has_violations": bool(violations),
                "close_reason": ctx.get("close_reason", ""),
                "created_at_ts": _to_ts(report.created_at),
            },
        )


# ── Strategy 문서 ─────────────────────────────────────────────────────────────

@dataclass
class StrategyDocument:
    """
    trade_strategy 컬렉션 문서.
    AI 시그널의 근거(기술·감성·시장구조 점수 + 이유)와
    실제 트레이드 결과를 결합하여 전략 패턴 검색에 활용한다.
    """
    point_id: str
    embed_text: str
    payload: dict[str, Any]

    @classmethod
    def from_journal(cls, journal: TradeJournal) -> "StrategyDocument":
        """
        TradeJournal의 ai_decision 필드에서 시그널 컨텍스트를 추출한다.
        ai_decision이 없는 수동 거래는 기본 텍스트로 대체한다.
        """
        is_win = float(journal.net_pnl) > 0
        ai: dict = journal.ai_decision or {}
        risk: dict = journal.risk_decision or {}

        confidence = ai.get("confidence")
        tech_score = ai.get("technical_score")
        sentiment_score = ai.get("sentiment_score")
        market_score = ai.get("market_score")
        reasons: list[str] = ai.get("reasons") or []

        parts = [
            f"{journal.coin} {journal.direction}",
            f"신뢰도 {confidence:.0%}" if confidence else "수동 거래",
            f"레버리지 {journal.leverage}x",
            f"결과: {journal.close_reason} | P&L {_pct_str(journal.pnl_percentage)}",
        ]

        if reasons:
            parts.append("시그널 근거: " + " | ".join(reasons[:4]))

        score_parts = []
        if tech_score is not None:
            score_parts.append(f"기술{float(tech_score):+.2f}")
        if sentiment_score is not None:
            score_parts.append(f"감성{float(sentiment_score):+.2f}")
        if market_score is not None:
            score_parts.append(f"시장{float(market_score):+.2f}")
        if score_parts:
            parts.append("점수: " + " | ".join(score_parts))

        return cls(
            point_id=str(journal.position_id),
            embed_text="\n".join(parts),
            payload={
                "source": "strategy",
                "user_id": str(journal.user_id),
                "position_id": str(journal.position_id),
                "journal_id": str(journal.id),
                "coin": journal.coin,
                "symbol": journal.symbol,
                "direction": journal.direction,
                "leverage": journal.leverage,
                "confidence": float(confidence) if confidence else None,
                "tech_score": float(tech_score) if tech_score else None,
                "sentiment_score": float(sentiment_score) if sentiment_score else None,
                "market_score": float(market_score) if market_score else None,
                "net_pnl": float(journal.net_pnl),
                "pnl_percentage": float(journal.pnl_percentage),
                "close_reason": journal.close_reason,
                "duration_seconds": journal.duration_seconds,
                "is_win": is_win,
                "is_ai_trade": journal.is_ai_trade,
                "rr_ratio": float(risk.get("risk_reward") or 0) or None,
                "entry_time_ts": _to_ts(journal.entry_time),
            },
        )
