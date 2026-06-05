"""
TechnicalAnalysisAgent — 멀티 타임프레임 분석 오케스트레이터.

AGENTS.md §2 완전 구현:
  1. 입력:  타임프레임별 OHLCV DataFrame dict
  2. 분석:  TechnicalAnalyzer로 타임프레임별 분석 (독립 실행)
  3. 집계:  TIMEFRAME_WEIGHTS로 가중 평균 → tech_score
  4. 출력:  TechnicalAnalysisResult

실패 정책:
  - 특정 타임프레임 실패 → score=0.0, 파이프라인 계속 (AGENTS.md §2.6)
  - 전체 실패 → tech_score=0.0 반환 (Synthesis에 None 전달 없이 중립)
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from agents.technical_analysis.analyzer import TechnicalAnalyzer
from agents.technical_analysis.indicators import detect_support_resistance
from agents.technical_analysis.models import TechnicalAnalysisResult, TimeframeAnalysis
from agents.technical_analysis.scorer import aggregate_timeframe_scores

logger = logging.getLogger(__name__)


class TechnicalAnalysisAgent:
    """
    Technical Analysis Agent.

    사용법:
        agent = TechnicalAnalysisAgent()
        ohlcv = {
            "1h":  pd.DataFrame(...),  # columns: open, high, low, close, volume
            "4h":  pd.DataFrame(...),
            "1d":  pd.DataFrame(...),
        }
        result = agent.run(ohlcv, coin="BTC", symbol="BTCUSDT")
        print(result.tech_score)          # -1.0 ~ +1.0
        print(result.to_dict("1h"))       # 1h 타임프레임 상세 JSON
    """

    def __init__(self) -> None:
        self._analyzer = TechnicalAnalyzer()

    def run(
        self,
        ohlcv_data: dict[str, pd.DataFrame],
        coin: str,
        symbol: Optional[str] = None,
    ) -> TechnicalAnalysisResult:
        """
        멀티 타임프레임 기술적 분석 실행.

        Args:
            ohlcv_data: {interval: DataFrame(open,high,low,close,volume)}
            coin:       "BTC" | "ETH"
            symbol:     "BTCUSDT" (None 시 coin+"USDT"로 자동 생성)

        Returns:
            TechnicalAnalysisResult
        """
        if symbol is None:
            symbol = f"{coin}USDT"

        timeframe_scores: dict[str, float] = {}
        analyses: dict[str, TimeframeAnalysis] = {}
        all_signals: list[str] = []

        for interval, df in ohlcv_data.items():
            try:
                result = self._analyzer.analyze(df, symbol, interval)
                if result is not None:
                    analyses[interval] = result
                    timeframe_scores[interval] = result.score
                    all_signals.extend(result.signals_fired)
                    logger.info(
                        "TA %s/%s score=%.3f signal=%s signals=%s",
                        symbol, interval, result.score, result.signal,
                        result.signals_fired,
                    )
                else:
                    logger.warning("TA skipped %s/%s (insufficient data)", symbol, interval)
                    timeframe_scores[interval] = 0.0

            except Exception as exc:
                logger.error("TA failed %s/%s: %s", symbol, interval, exc, exc_info=True)
                timeframe_scores[interval] = 0.0

        tech_score = aggregate_timeframe_scores(timeframe_scores)

        # 지지/저항선: 데이터가 가장 풍부한 타임프레임에서 추출
        support_levels, resistance_levels = self._extract_sr_levels(ohlcv_data)

        latest_close = self._get_latest_close(ohlcv_data)

        logger.info(
            "TA complete %s tech_score=%.3f timeframes=%s",
            symbol, tech_score, list(timeframe_scores.keys()),
        )

        return TechnicalAnalysisResult(
            coin=coin,
            symbol=symbol,
            tech_score=tech_score,
            timeframe_scores=timeframe_scores,
            analyses=analyses,
            signals_fired=list(set(all_signals)),  # 중복 제거
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            latest_close=latest_close,
        )

    # ── 내부 메서드 ───────────────────────────────────────────────────────────

    @staticmethod
    def _extract_sr_levels(
        ohlcv_data: dict[str, pd.DataFrame],
    ) -> tuple[list[float], list[float]]:
        """가장 긴 DataFrame에서 지지/저항선 추출."""
        best_df: Optional[pd.DataFrame] = None

        for df in ohlcv_data.values():
            if df is not None and not df.empty:
                if best_df is None or len(df) > len(best_df):
                    best_df = df

        if best_df is None or len(best_df) < 10:
            return [], []

        try:
            return detect_support_resistance(best_df, pivot_window=5, n_levels=3)
        except Exception as exc:
            logger.error("S/R detection failed: %s", exc)
            return [], []

    @staticmethod
    def _get_latest_close(ohlcv_data: dict[str, pd.DataFrame]) -> float:
        """가장 최근 close 가격 반환 (우선순위: 1m > 5m > 15m > ...)."""
        priority = ["1m", "5m", "15m", "1h", "4h", "1d"]
        for interval in priority:
            df = ohlcv_data.get(interval)
            if df is not None and not df.empty and "close" in df.columns:
                val = df["close"].iloc[-1]
                if not (val != val):  # NaN check
                    return float(val)
        return 0.0
