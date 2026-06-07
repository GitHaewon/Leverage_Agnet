"""
AI Analyst Agent 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

import json
from typing import Any

from agents.analyst.models import (
    AnalysisDecision,
    AnalystResult,
    MarketContext,
    StrategyContext,
    TechnicalContext,
)


# ── 입력 헬퍼 ────────────────────────────────────────────────────────────────────

def make_market(**kwargs: Any) -> MarketContext:
    defaults: dict[str, Any] = dict(
        coin="BTC",
        symbol="BTCUSDT",
        current_price=67450.0,
    )
    defaults.update(kwargs)
    return MarketContext(**defaults)


def make_technical(**kwargs: Any) -> TechnicalContext:
    defaults: dict[str, Any] = dict(
        tech_score=0.72,
        timeframe_scores={"1d": 0.80, "4h": 0.75, "1h": 0.65},
        indicators={
            "rsi_1h": 42.3,
            "rsi_4h": 38.1,
            "macd_1h": {"macd": 125.4, "signal": 89.2, "histogram": 36.2},
            "ema_1h": {"ema9": 67480.0, "ema21": 67250.0, "ema200": 64200.0},
        },
        signals_fired=["rsi_oversold_4h", "ema200_support_1h", "macd_bullish_cross_1h"],
        support_levels=[66800.0, 66200.0, 65500.0],
        resistance_levels=[68200.0, 69000.0, 70000.0],
    )
    defaults.update(kwargs)
    return TechnicalContext(**defaults)


def make_strategy(**kwargs: Any) -> StrategyContext:
    defaults: dict[str, Any] = dict(
        sentiment_score=-0.31,
        fear_greed_index=42,
        fear_greed_label="Fear",
        dominant_sentiment="negative",
        news_items=[
            {"headline": "BTC rally expected", "source": "CoinDesk", "sentiment": "positive"},
        ],
        market_score=0.58,
        funding_rate=-0.0002,
        oi_1h_change_pct=0.8,
        long_short_ratio=0.89,
        long_account_pct=47.1,
        whale_activity="accumulating",
    )
    defaults.update(kwargs)
    return StrategyContext(**defaults)


def make_neutral_technical() -> TechnicalContext:
    return TechnicalContext(
        tech_score=0.0,
        timeframe_scores={},
        indicators={},
        signals_fired=[],
        support_levels=[],
        resistance_levels=[],
    )


def make_neutral_strategy() -> StrategyContext:
    return StrategyContext()


# ── Claude 응답 JSON 빌더 ─────────────────────────────────────────────────────────

def make_claude_response(
    decision: str = "LONG",
    confidence: int = 82,
    reason: str = "RSI(14)=42.3 과매도 + EMA200 지지 확인, 고래 매수 포착",
    risk_level: str = "MEDIUM",
    entry_price: float = 67450.0,
    take_profit: float = 69200.0,
    stop_loss: float = 66800.0,
    leverage: int = 5,
    rr_ratio: float = 2.71,
    raw_reasons: list[str] | None = None,
) -> str:
    if raw_reasons is None:
        raw_reasons = [
            "RSI(14) = 42.3 과매도 구간 진입",
            "Funding Rate -0.02% 숏 과다 구조",
            "EMA200($64,200) 지지선 접근 후 고래 매수",
        ]
    return json.dumps({
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
        "risk_level": risk_level,
        "entry_price": entry_price,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "leverage": leverage,
        "rr_ratio": rr_ratio,
        "raw_reasons": raw_reasons,
    }, ensure_ascii=False)


def make_hold_response(reason: str = "불확실한 시장 구조") -> str:
    return json.dumps({
        "decision": "HOLD",
        "confidence": 45,
        "reason": reason,
        "risk_level": "HIGH",
        "entry_price": 0.0,
        "take_profit": None,
        "stop_loss": None,
        "leverage": 1,
        "rr_ratio": 0.0,
        "raw_reasons": [reason],
    }, ensure_ascii=False)


def make_markdown_response(inner_json: str) -> str:
    """마크다운 코드블록으로 감싼 응답."""
    return f"```json\n{inner_json}\n```"


# ── 테스트용 Stub Client ──────────────────────────────────────────────────────────

class StubAnthropicClient:
    """고정 응답을 반환하는 테스트용 Anthropic 클라이언트."""

    def __init__(
        self,
        response_text: str = "",
        tokens_in: int = 100,
        tokens_out: int = 50,
    ) -> None:
        self._text = response_text or make_claude_response()
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.call_count = 0
        self.last_messages: list[dict] = []
        self.last_system: str = ""
        self.last_model: str = ""

    async def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        temperature: float,
    ) -> tuple[str, int, int]:
        self.call_count += 1
        self.last_messages = messages
        self.last_system = system
        self.last_model = model
        return self._text, self._tokens_in, self._tokens_out


class FailingAnthropicClient:
    """항상 예외를 발생시키는 테스트용 클라이언트."""

    def __init__(self, error: str = "API 오류") -> None:
        self._error = error

    async def create_message(self, **_: Any) -> tuple[str, int, int]:
        raise RuntimeError(self._error)
