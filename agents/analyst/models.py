"""
AI Analyst Agent 데이터 모델.

순수 Python dataclass — 외부 의존성 없음.

설계 원칙:
  - AnalysisDecision: 공개 API 출력 (주문 권한 없음)
  - AnalystResult:    내부 전체 결과 (Risk Agent 전달용 추가 데이터 포함)
  - MarketContext / TechnicalContext / StrategyContext: 세 종류의 입력
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── 입력 모델 ────────────────────────────────────────────────────────────────────

@dataclass
class MarketContext:
    """현재 시장 상태 (Market Data Agent 출력)."""
    coin: str              # "BTC" | "ETH"
    symbol: str            # "BTCUSDT" | "ETHUSDT"
    current_price: float


@dataclass
class TechnicalContext:
    """기술적 분석 결과 (Technical Analysis Agent 출력)."""
    tech_score: float                    # -1.0 ~ +1.0
    timeframe_scores: dict[str, float]   # {"1d": 0.8, "4h": 0.75, ...}
    indicators: dict                     # rsi, macd, bb, ema, volume, atr
    signals_fired: list[str]             # ["rsi_oversold_4h", ...]
    support_levels: list[float]
    resistance_levels: list[float]


@dataclass
class StrategyContext:
    """감성·시장구조 분석 결과 (Sentiment + Market Structure Agent 출력).

    두 에이전트가 실패한 경우 중립값(기본값)을 사용한다.
    """
    sentiment_score: float = 0.0
    fear_greed_index: int = 50
    fear_greed_label: str = "Neutral"
    dominant_sentiment: str = "neutral"
    news_items: list[dict] = field(default_factory=list)

    market_score: float = 0.0
    funding_rate: float = 0.0
    oi_1h_change_pct: float = 0.0
    long_short_ratio: float = 1.0
    long_account_pct: float = 50.0
    whale_activity: str = "neutral"


# ── 출력 모델 ────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisDecision:
    """
    공개 출력 — 사용자 API 응답 및 UI 표시용.

    AI는 분석만 수행한다. 이 객체는 주문 권한을 갖지 않는다.
    """
    decision: Literal["LONG", "SHORT", "HOLD"]
    confidence: int                        # 0 ~ 100 정수
    reason: str                            # 한국어 요약 한 줄
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]


@dataclass
class AnalystResult:
    """
    AI 분석 전체 결과.

    decision: 공개 출력
    나머지 필드: Risk Agent로 전달하는 내부 상세 데이터 (가격, 레버리지 등)

    forced_hold=True이면 Claude 원본 결과가 Safety Rule로 HOLD 강제 변환된 것.
    """
    decision: AnalysisDecision

    # Risk Agent 전달용
    entry_price: float
    take_profit: float | None
    stop_loss: float | None
    leverage: int
    rr_ratio: float
    raw_reasons: list[str]

    # 메타
    model_used: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    forced_hold: bool = False   # Safety Rule로 HOLD 강제된 경우
    hold_reason: str = ""       # forced_hold=True 시 사유

    @property
    def is_actionable(self) -> bool:
        """LONG 또는 SHORT 결정이면 True."""
        return self.decision.decision != "HOLD"
