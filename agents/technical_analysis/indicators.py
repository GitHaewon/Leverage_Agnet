"""
기술적 지표 계산 — 순수 함수 집합.

외부 라이브러리 없이 pandas/numpy만 사용한다.
모든 함수는 NaN-safe이며, 데이터 부족 시 NaN 시리즈를 반환한다.

최소 데이터 요구사항:
  RSI(14):        ≥ 15 rows
  MACD(12,26,9):  ≥ 35 rows
  EMA(200):       ≥ 200 rows (부족 시 NaN)
  BB(20):         ≥ 21 rows
  ATR(14):        ≥ 15 rows
  VWAP:           ≥ 1 row (세션 기준 리셋)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_ROWS_RSI = 15
MIN_ROWS_MACD = 35
MIN_ROWS_BB = 21
MIN_ROWS_ATR = 15
MIN_ROWS_VWAP = 1


# ── RSI ───────────────────────────────────────────────────────────────────────

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI (Relative Strength Index).

    RSI = 100 - 100 / (1 + RS)
    RS  = Avg(gains, period) / Avg(losses, period)
    Wilder's smoothing = EWM(com=period-1)
    """
    if len(close) < period + 1:
        return pd.Series([float("nan")] * len(close), index=close.index)

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    avg_gain = gains.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    # avg_loss = 0 이고 avg_gain > 0 → RSI = 100 (완전 상승 추세)
    # avg_loss = 0 이고 avg_gain = 0 → RSI = NaN (횡보)
    rs = avg_gain / avg_loss.where(avg_loss > 0, other=float("nan"))
    rsi = 100 - (100 / (1 + rs))
    # 손실이 전혀 없는 구간은 RSI=100 (NaN으로 남기지 않음)
    no_loss_mask = (avg_loss == 0) & (avg_gain > 0)
    rsi = rsi.copy()
    rsi[no_loss_mask] = 100.0
    return rsi


# ── MACD ──────────────────────────────────────────────────────────────────────

def calculate_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence Divergence).

    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ── EMA ───────────────────────────────────────────────────────────────────────

def calculate_ema(close: pd.Series, period: int) -> pd.Series:
    """지수 이동 평균 (Exponential Moving Average)."""
    return close.ewm(span=period, adjust=False).mean()


# ── ATR ───────────────────────────────────────────────────────────────────────

def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    ATR (Average True Range) — Wilder's smoothing.

    TR = max(H-L, |H-Prev_C|, |L-Prev_C|)
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period, adjust=False).mean()


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def calculate_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Returns: (upper, middle, lower)
    middle = SMA(period)
    upper  = middle + std_dev × rolling_std
    lower  = middle - std_dev × rolling_std
    """
    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


# ── VWAP ──────────────────────────────────────────────────────────────────────

def calculate_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    VWAP (Volume Weighted Average Price) — 일별 세션 기준 리셋.

    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    Typical Price = (H + L + C) / 3

    날짜 경계에서 리셋되므로 인트라데이 VWAP이다.
    멀티 데이 데이터는 groupby(date)로 계산한다.
    """
    tp = (high + low + close) / 3

    if isinstance(close.index, pd.DatetimeIndex):
        dates = close.index.date
        cumtp_vol = (tp * volume).groupby(dates, group_keys=False).cumsum()
        cumvol = volume.groupby(dates, group_keys=False).cumsum()
    else:
        cumtp_vol = (tp * volume).cumsum()
        cumvol = volume.cumsum()

    return cumtp_vol / cumvol.replace(0, float("nan"))


# ── Volume MA ─────────────────────────────────────────────────────────────────

def calculate_volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    """거래량 이동 평균."""
    return volume.rolling(window=period, min_periods=1).mean()


# ── Support / Resistance ──────────────────────────────────────────────────────

def detect_support_resistance(
    df: pd.DataFrame,
    pivot_window: int = 5,
    n_levels: int = 3,
) -> tuple[list[float], list[float]]:
    """
    피봇 포인트 기반 지지/저항선 감지 (AGENTS.md §2.4).

    center=True rolling: 양쪽 5봉 이내 local min/max 찾기.
    Returns: (support_levels, resistance_levels) — 최근 n_levels개
    """
    resistance = df["high"].rolling(pivot_window, center=True).max()
    support = df["low"].rolling(pivot_window, center=True).min()

    resistance_levels = (
        resistance.dropna()
        .drop_duplicates()
        .sort_values(ascending=False)
        .head(n_levels)
        .tolist()
    )
    support_levels = (
        support.dropna()
        .drop_duplicates()
        .sort_values()
        .head(n_levels)
        .tolist()
    )
    return support_levels, resistance_levels
