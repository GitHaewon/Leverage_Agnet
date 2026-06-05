"""
TechnicalAnalyzer — 단일 타임프레임 OHLCV 분석.

입력:  pandas DataFrame (columns: open, high, low, close, volume)
       DatetimeIndex (UTC) 권장, 오름차순 정렬

출력:  TimeframeAnalysis dataclass

시그널 감지 규칙:
  rsi_oversold        RSI ≤ 30
  rsi_overbought      RSI ≥ 70
  macd_bullish_cross  MACD histogram: 음 → 양 전환
  macd_bearish_cross  MACD histogram: 양 → 음 전환
  bb_lower_touch      %B ≤ 0.05 (하단 밴드 터치)
  bb_upper_touch      %B ≥ 0.95 (상단 밴드 터치)
  ema200_support      현재가가 EMA200 위 1% 이내
  ema200_resistance   현재가가 EMA200 아래 1% 이내
  volume_surge        거래량 > 1.5× MA20
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from agents.technical_analysis.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_volume_ma,
    calculate_vwap,
)
from agents.technical_analysis.models import (
    BollingerBandsResult,
    EMAResult,
    MACDResult,
    TimeframeAnalysis,
)
from agents.technical_analysis.scorer import (
    calculate_timeframe_score,
    calculate_trend_score,
    calculate_momentum_score,
    calculate_volatility_score,
    determine_bb_position,
    determine_ema_alignment,
    determine_macd_cross,
    score_bollinger,
    score_ema_alignment,
    score_macd,
    score_rsi,
    score_to_signal,
    score_volume,
)

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}
_MIN_ROWS = 30  # 최소 의미있는 분석을 위한 행 수


class TechnicalAnalyzer:
    """
    단일 타임프레임 기술적 분석기.

    설계:
      - 데이터 부족 시 가능한 지표만 계산 (안전 폴백)
      - 모든 내부 계산은 float (Decimal 미사용, 속도 우선)
      - NaN 값은 0.0 점수로 폴백
    """

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        interval: str,
    ) -> Optional[TimeframeAnalysis]:
        """
        OHLCV DataFrame을 받아 단일 타임프레임 분석을 수행한다.

        Returns:
            TimeframeAnalysis | None (데이터 부족 시)
        """
        if not self._validate(df, symbol, interval):
            return None

        df = df.copy().sort_index()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        latest_close = float(close.iloc[-1])

        # ── 지표 계산 ────────────────────────────────────────────────────────
        rsi_series = calculate_rsi(close, period=14)
        macd_line, signal_line, histogram = calculate_macd(close)
        ema9_s   = calculate_ema(close, 9)
        ema21_s  = calculate_ema(close, 21)
        ema50_s  = calculate_ema(close, 50)
        ema200_s = calculate_ema(close, 200)
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close, 20, 2.0)
        atr_series = calculate_atr(high, low, close, 14)
        vwap_series = calculate_vwap(high, low, close, volume)
        vol_ma = calculate_volume_ma(volume, 20)

        # ── 최신값 추출 ───────────────────────────────────────────────────────
        rsi_val   = self._last_valid(rsi_series, 50.0)
        macd_val  = self._last_valid(macd_line)
        sig_val   = self._last_valid(signal_line)
        hist_val  = self._last_valid(histogram)
        prev_hist = self._nth_last(histogram, 2)
        ema9      = self._last_valid(ema9_s,   latest_close)
        ema21     = self._last_valid(ema21_s,  latest_close)
        ema50     = self._last_valid(ema50_s,  latest_close)
        ema200    = self._last_valid(ema200_s, latest_close)
        bb_u      = self._last_valid(bb_upper,  latest_close)
        bb_m      = self._last_valid(bb_middle, latest_close)
        bb_l      = self._last_valid(bb_lower,  latest_close)
        atr_val   = self._last_valid(atr_series)
        prev_atr  = self._nth_last(atr_series, 2)
        vwap_val  = self._last_valid(vwap_series, latest_close)
        vol_now   = float(volume.iloc[-1]) if len(volume) else 0.0
        vol_ma20  = self._last_valid(vol_ma, 1.0)

        # ── 복합 객체 구성 ────────────────────────────────────────────────────
        bb_pct_b = (
            (latest_close - bb_l) / (bb_u - bb_l)
            if (bb_u - bb_l) > 0 else 0.5
        )
        bb_bandwidth = (
            (bb_u - bb_l) / bb_m * 100 if bb_m > 0 else 0.0
        )

        macd_result = MACDResult(
            macd=macd_val,
            signal=sig_val,
            histogram=hist_val,
            cross=determine_macd_cross(hist_val, prev_hist),
        )
        ema_result = EMAResult(
            ema9=ema9,
            ema21=ema21,
            ema50=ema50,
            ema200=ema200,
            alignment=determine_ema_alignment(ema9, ema21, ema50, ema200),
        )
        bb_result = BollingerBandsResult(
            upper=bb_u,
            middle=bb_m,
            lower=bb_l,
            position=determine_bb_position(latest_close, bb_u, bb_l),
            bandwidth=bb_bandwidth,
            percent_b=bb_pct_b,
        )

        # ── 점수 계산 ─────────────────────────────────────────────────────────
        ema_score    = score_ema_alignment(ema9, ema21, ema50, ema200)
        macd_score   = score_macd(hist_val, prev_hist)
        rsi_score    = score_rsi(rsi_val)
        bb_score     = score_bollinger(latest_close, bb_u, bb_l, bb_m)
        vol_score    = score_volume(vol_now, vol_ma20)
        vol_ratio    = vol_now / vol_ma20 if vol_ma20 > 0 else 1.0

        trend_score      = calculate_trend_score(ema_score, macd_score)
        momentum_score   = calculate_momentum_score(rsi_score)
        volatility_score = calculate_volatility_score(bb_score, atr_val, prev_atr)
        timeframe_score  = calculate_timeframe_score(
            trend_score, momentum_score, volatility_score, vol_score
        )
        signal = score_to_signal(timeframe_score)

        # ── 시그널 감지 ───────────────────────────────────────────────────────
        signals = self._detect_signals(
            interval=interval,
            rsi=rsi_val,
            hist=hist_val,
            prev_hist=prev_hist,
            close=latest_close,
            bb_u=bb_u,
            bb_l=bb_l,
            bb_pct_b=bb_pct_b,
            ema200=ema200,
            vol_ratio=vol_ratio,
        )

        return TimeframeAnalysis(
            symbol=symbol,
            timeframe=interval,
            close=latest_close,
            rsi=rsi_val,
            macd=macd_result,
            ema=ema_result,
            atr=atr_val,
            vwap=vwap_val,
            bollinger_bands=bb_result,
            volume_ratio=vol_ratio,
            score=timeframe_score,
            signal=signal,
            signals_fired=signals,
        )

    # ── 시그널 감지 로직 ──────────────────────────────────────────────────────

    @staticmethod
    def _detect_signals(
        interval: str,
        rsi: float,
        hist: float,
        prev_hist: float,
        close: float,
        bb_u: float,
        bb_l: float,
        bb_pct_b: float,
        ema200: float,
        vol_ratio: float,
    ) -> list[str]:
        signals: list[str] = []
        sfx = f"_{interval}"  # e.g., "_1h"

        if rsi <= 30:
            signals.append(f"rsi_oversold{sfx}")
        elif rsi >= 70:
            signals.append(f"rsi_overbought{sfx}")

        if hist > 0 and prev_hist <= 0:
            signals.append(f"macd_bullish_cross{sfx}")
        elif hist < 0 and prev_hist >= 0:
            signals.append(f"macd_bearish_cross{sfx}")

        if bb_pct_b <= 0.05:
            signals.append(f"bb_lower_touch{sfx}")
        elif bb_pct_b >= 0.95:
            signals.append(f"bb_upper_touch{sfx}")

        if ema200 > 0:
            dist_pct = (close - ema200) / ema200
            if 0 < dist_pct <= 0.01:          # EMA200 위 1% 이내
                signals.append(f"ema200_support{sfx}")
            elif -0.01 <= dist_pct < 0:        # EMA200 아래 1% 이내
                signals.append(f"ema200_resistance{sfx}")

        if vol_ratio >= 1.5:
            signals.append(f"volume_surge{sfx}")

        return signals

    # ── 유틸 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate(df: pd.DataFrame, symbol: str, interval: str) -> bool:
        if df is None or df.empty:
            logger.warning("Empty DataFrame for %s/%s", symbol, interval)
            return False
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            logger.warning("Missing columns %s for %s/%s", missing, symbol, interval)
            return False
        if len(df) < _MIN_ROWS:
            logger.warning(
                "Insufficient data (%d < %d) for %s/%s",
                len(df), _MIN_ROWS, symbol, interval,
            )
            return False
        return True

    @staticmethod
    def _last_valid(series: pd.Series, fallback: float = 0.0) -> float:
        """시리즈에서 마지막 유효한 (비-NaN) 값 반환."""
        valid = series.dropna()
        if valid.empty:
            return fallback
        return float(valid.iloc[-1])

    @staticmethod
    def _nth_last(series: pd.Series, n: int, fallback: float = 0.0) -> float:
        """시리즈에서 끝에서 n번째 유효한 값 반환."""
        valid = series.dropna()
        if len(valid) < n:
            return fallback
        return float(valid.iloc[-n])
