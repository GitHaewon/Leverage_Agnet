"""
Technical Analysis Agent 출력 모델.

외부 의존성 없는 순수 Python dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Signal = Literal["BULLISH", "NEUTRAL", "BEARISH"]


@dataclass
class MACDResult:
    macd: float
    signal: float
    histogram: float
    cross: Literal["bullish", "bearish", "neutral"]

    def to_dict(self) -> dict:
        return {
            "macd": round(self.macd, 4),
            "signal": round(self.signal, 4),
            "histogram": round(self.histogram, 4),
            "cross": self.cross,
        }


@dataclass
class EMAResult:
    ema9: float
    ema21: float
    ema50: float
    ema200: float
    alignment: Literal["bullish", "bearish", "mixed"]

    def to_dict(self) -> dict:
        return {
            "ema9": round(self.ema9, 2),
            "ema21": round(self.ema21, 2),
            "ema50": round(self.ema50, 2),
            "ema200": round(self.ema200, 2),
            "alignment": self.alignment,
        }


@dataclass
class BollingerBandsResult:
    upper: float
    middle: float
    lower: float
    position: Literal["upper_third", "middle", "lower_third"]
    bandwidth: float       # (upper - lower) / middle × 100 (%)
    percent_b: float       # (close - lower) / (upper - lower)

    def to_dict(self) -> dict:
        return {
            "upper": round(self.upper, 2),
            "middle": round(self.middle, 2),
            "lower": round(self.lower, 2),
            "position": self.position,
            "bandwidth_pct": round(self.bandwidth, 2),
            "percent_b": round(self.percent_b, 4),
        }


@dataclass
class TimeframeAnalysis:
    """단일 타임프레임 기술적 분석 결과 — 요청 JSON 포맷 포함."""

    symbol: str
    timeframe: str
    close: float

    rsi: float
    macd: MACDResult
    ema: EMAResult
    atr: float
    vwap: float
    bollinger_bands: BollingerBandsResult

    volume_ratio: float     # 현재 거래량 / MA20 거래량
    score: float            # -1.0 ~ +1.0
    signal: Signal
    signals_fired: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """요청 포맷 JSON 출력."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "close": round(self.close, 2),
            "rsi": round(self.rsi, 2),
            "macd": self.macd.to_dict(),
            "ema": self.ema.to_dict(),
            "bollinger_bands": self.bollinger_bands.to_dict(),
            "atr": round(self.atr, 2),
            "vwap": round(self.vwap, 2),
            "volume_ratio": round(self.volume_ratio, 3),
            "score": round(self.score, 4),
            "signal": self.signal,
            "signals_fired": self.signals_fired,
        }


@dataclass
class TechnicalAnalysisResult:
    """멀티 타임프레임 집계 결과 (AGENTS.md §2.3 출력 포맷)."""

    coin: str
    symbol: str
    tech_score: float                           # -1.0 ~ +1.0 (멀티 TF 가중 평균)
    timeframe_scores: dict[str, float]          # {"1h": 0.65, ...}
    analyses: dict[str, TimeframeAnalysis]      # {"1h": TimeframeAnalysis, ...}
    signals_fired: list[str]                    # 모든 타임프레임 통합 시그널
    support_levels: list[float]
    resistance_levels: list[float]
    latest_close: float

    def to_dict(self, timeframe: str | None = None) -> dict:
        """
        timeframe 지정 시 해당 타임프레임 상세 JSON 반환.
        지정 없으면 전체 집계 결과 반환.
        """
        if timeframe and timeframe in self.analyses:
            return self.analyses[timeframe].to_dict()

        return {
            "coin": self.coin,
            "symbol": self.symbol,
            "tech_score": round(self.tech_score, 4),
            "timeframe_scores": {k: round(v, 4) for k, v in self.timeframe_scores.items()},
            "signals_fired": self.signals_fired,
            "support_levels": [round(s, 2) for s in self.support_levels],
            "resistance_levels": [round(r, 2) for r in self.resistance_levels],
            "latest_close": round(self.latest_close, 2),
        }
