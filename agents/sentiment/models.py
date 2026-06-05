"""
Sentiment Agent 데이터 모델.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

FEAR_GREED_LABELS: dict[tuple[int, int], str] = {
    (0, 24):  "Extreme Fear",
    (25, 44): "Fear",
    (45, 55): "Neutral",
    (56, 74): "Greed",
    (75, 100): "Extreme Greed",
}

NEWS_WEIGHTS = {"news": 0.65, "fear_greed": 0.35}


def label_fear_greed(index: int) -> str:
    for (lo, hi), label in FEAR_GREED_LABELS.items():
        if lo <= index <= hi:
            return label
    return "Unknown"


@dataclass
class NewsItem:
    headline: str
    source: str
    published_at: str           # ISO 8601
    sentiment: Literal["positive", "negative", "neutral"]
    confidence: float           # 0.0 ~ 1.0
    score: float                # +confidence (pos) / -confidence (neg) / 0 (neutral)


@dataclass
class FearGreedData:
    index: int                  # 0 ~ 100
    label: str
    score: float                # normalized (-1.0 ~ +1.0)


@dataclass
class SentimentResult:
    coin: str
    sentiment_score: float      # 종합 (-1.0 ~ +1.0)
    news_score: float
    fear_greed_score: float
    fear_greed_index: int
    fear_greed_label: str
    dominant_sentiment: Literal["positive", "negative", "neutral"]
    news_items: list[NewsItem] = field(default_factory=list)
    news_analyzed: int = 0
    cache_used: bool = False

    @classmethod
    def neutral(cls, coin: str, *, cache_used: bool = False) -> "SentimentResult":
        return cls(
            coin=coin,
            sentiment_score=0.0,
            news_score=0.0,
            fear_greed_score=0.0,
            fear_greed_index=50,
            fear_greed_label="Neutral",
            dominant_sentiment="neutral",
            news_analyzed=0,
            cache_used=cache_used,
        )


@dataclass
class SentimentInput:
    coin: str
    news_count: int = 20
    news_lookback_hours: int = 4
