"""
Synthesis Agent 데이터 모델.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from agents.risk.models import RawSignal
from decimal import Decimal
import uuid


@dataclass
class SynthesisInput:
    """세 에이전트 점수를 종합하는 Synthesis Agent 입력."""
    coin: str
    symbol: str
    current_price: float

    # Technical Analysis
    tech_score: float
    support_levels: list[float]
    resistance_levels: list[float]
    tech_indicators: dict          # TechnicalAnalysisResult에서 추출한 지표 딕셔너리

    # Sentiment
    sentiment_score: float
    fear_greed_index: int
    fear_greed_label: str
    dominant_sentiment: str
    news_items: list[dict]         # NewsItem → dict 변환본

    # Market Structure
    market_score: float
    funding_rate: float
    oi_1h_change_pct: float
    long_short_ratio: float
    long_account_pct: float
    whale_activity: str


@dataclass
class SynthesisResult:
    """Claude Sonnet이 생성한 트레이딩 시그널."""
    direction: Literal["LONG", "SHORT", "HOLD"]
    confidence: float
    entry_price: float
    take_profit: Optional[float]
    stop_loss: Optional[float]
    leverage: int
    rr_ratio: float
    reasons: list[str]

    # 메타
    model_used: str = "claude-sonnet-4-6"
    tokens_input: int = 0
    tokens_output: int = 0
    synthesis_skipped: bool = False  # 하위 에이전트 전부 실패 시
    raw_response: str = ""

    def to_raw_signal(self, symbol: str) -> RawSignal:
        """RawSignal로 변환하여 Risk Agent에 전달한다."""
        return RawSignal(
            direction=self.direction,
            coin=self.extract_coin(symbol),
            symbol=symbol,
            confidence=self.confidence,
            entry_price=Decimal(str(self.entry_price)),
            take_profit=Decimal(str(self.take_profit)) if self.take_profit else None,
            stop_loss=Decimal(str(self.stop_loss)) if self.stop_loss else None,
            leverage=self.leverage,
            signal_id=uuid.uuid4(),
        )

    @staticmethod
    def extract_coin(symbol: str) -> str:
        return symbol.replace("USDT", "")

    @classmethod
    def hold(cls, *, reason: str = "HOLD 시그널", skipped: bool = False) -> "SynthesisResult":
        return cls(
            direction="HOLD", confidence=0.0,
            entry_price=0.0, take_profit=None, stop_loss=None,
            leverage=1, rr_ratio=0.0,
            reasons=[reason], synthesis_skipped=skipped,
        )
