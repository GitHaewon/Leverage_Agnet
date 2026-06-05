"""
Strategy 테스트 공통 픽스처 헬퍼.

직접 import하여 사용: from tests.unit.agents._strategy_fixtures import ...
"""
from __future__ import annotations

from agents.technical_analysis.models import (
    BollingerBandsResult,
    EMAResult,
    MACDResult,
    TechnicalAnalysisResult,
    TimeframeAnalysis,
)


def make_tf_analysis(
    *,
    close: float = 67450.0,
    rsi: float = 50.0,
    macd_hist: float = 0.0,
    macd_cross: str = "neutral",
    ema9:   float = 67500.0,
    ema21:  float = 67400.0,
    ema50:  float = 67200.0,
    ema200: float = 65000.0,
    atr: float = 300.0,
    vwap: float = 67450.0,
    bb_upper:  float = 68500.0,
    bb_middle: float = 67500.0,
    bb_lower:  float = 66500.0,
    pct_b: float = 0.50,
    volume_ratio: float = 1.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
) -> TimeframeAnalysis:
    """테스트용 TimeframeAnalysis 생성 헬퍼."""
    from agents.technical_analysis.scorer import (
        determine_ema_alignment,
        determine_macd_cross,
        determine_bb_position,
        score_to_signal,
    )

    ema_align = determine_ema_alignment(ema9, ema21, ema50, ema200)
    bb_pos    = determine_bb_position(close, bb_upper, bb_lower)
    signal    = score_to_signal(0.0)

    bandwidth = ((bb_upper - bb_lower) / bb_middle * 100) if bb_middle else 0.0

    return TimeframeAnalysis(
        symbol=symbol,
        timeframe=timeframe,
        close=close,
        rsi=rsi,
        macd=MACDResult(
            macd=0.0,
            signal=0.0,
            histogram=macd_hist,
            cross=macd_cross,  # type: ignore[arg-type]
        ),
        ema=EMAResult(
            ema9=ema9,
            ema21=ema21,
            ema50=ema50,
            ema200=ema200,
            alignment=ema_align,  # type: ignore[arg-type]
        ),
        atr=atr,
        vwap=vwap,
        bollinger_bands=BollingerBandsResult(
            upper=bb_upper,
            middle=bb_middle,
            lower=bb_lower,
            position=bb_pos,  # type: ignore[arg-type]
            bandwidth=bandwidth,
            percent_b=pct_b,
        ),
        volume_ratio=volume_ratio,
        score=0.0,
        signal=signal,  # type: ignore[arg-type]
        signals_fired=[],
    )


def make_ta_result(
    coin: str,
    symbol: str,
    *,
    analyses: dict[str, TimeframeAnalysis] | None = None,
    tech_score: float = 0.0,
    support_levels: list[float] | None = None,
    resistance_levels: list[float] | None = None,
    latest_close: float = 67450.0,
) -> TechnicalAnalysisResult:
    """테스트용 TechnicalAnalysisResult 생성 헬퍼."""
    _analyses = analyses or {}
    return TechnicalAnalysisResult(
        coin=coin,
        symbol=symbol,
        tech_score=tech_score,
        timeframe_scores={tf: 0.0 for tf in _analyses},
        analyses=_analyses,
        signals_fired=[],
        support_levels=support_levels or [66000.0, 65000.0, 64000.0],
        resistance_levels=resistance_levels or [69000.0, 70000.0, 71000.0],
        latest_close=latest_close,
    )
