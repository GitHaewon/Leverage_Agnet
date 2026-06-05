"""
Technical Analysis Agent — OHLCV 기반 기술적 지표 계산 + 방향성 점수 산출.

AGENTS.md §2 구현:
  - 지표: RSI, MACD, EMA(9/21/50/200), ATR, VWAP, Bollinger Bands
  - 타임프레임 가중치: 1d=0.30 / 4h=0.25 / 1h=0.20 / 15m=0.15 / 5m=0.07 / 1m=0.03
  - 지표 범주 가중치: trend=0.35 / momentum=0.30 / volatility=0.20 / volume=0.15
  - 출력: tech_score (-1.0 ~ +1.0) + 타임프레임별 점수 + 발화된 시그널

사용법:
    import pandas as pd
    from agents.technical_analysis import TechnicalAnalysisAgent

    agent = TechnicalAnalysisAgent()
    # ohlcv_data: {"1h": pd.DataFrame(columns=[open,high,low,close,volume])}
    result = agent.run(ohlcv_data, coin="BTC")
    print(result.tech_score)           # -1.0 ~ +1.0
    print(result.to_dict("15m"))       # 타임프레임별 JSON 출력
"""
from agents.technical_analysis.agent import TechnicalAnalysisAgent
from agents.technical_analysis.models import (
    TechnicalAnalysisResult,
    TimeframeAnalysis,
)

__all__ = [
    "TechnicalAnalysisAgent",
    "TechnicalAnalysisResult",
    "TimeframeAnalysis",
]
