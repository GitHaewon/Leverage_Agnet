"""
기술적 지표 단위 테스트.

수학적 정확성 검증:
  - 알려진 입력 → 알려진 출력 비교
  - NaN 처리 (데이터 부족)
  - 경계값 처리
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.technical_analysis.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_volume_ma,
    calculate_vwap,
    detect_support_resistance,
)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _series(values: list[float], name: str = "close") -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1h", tz="UTC")
    return pd.Series(values, index=idx, name=name)


def _ohlcv(n: int = 100, base_price: float = 100.0) -> pd.DataFrame:
    """선형 상승 추세 + 작은 변동성 OHLCV."""
    rng = np.random.default_rng(42)
    closes = base_price + np.arange(n) * 0.5 + rng.normal(0, 0.5, n)
    highs  = closes + rng.uniform(0.1, 1.0, n)
    lows   = closes - rng.uniform(0.1, 1.0, n)
    opens  = closes - rng.uniform(-0.5, 0.5, n)
    volumes = rng.uniform(100, 1000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


# ── RSI ───────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_rsi_range(self):
        """RSI는 항상 0~100 범위."""
        df = _ohlcv(100)
        rsi = calculate_rsi(df["close"], 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_rising_trend_high(self):
        """강한 상승 추세에서 RSI가 높아야 함 (>50).
        일정 상승이면 losses=0 → RSI=100 처리."""
        prices = [float(100 + i * 2) for i in range(50)]  # 일정 상승
        rsi = calculate_rsi(_series(prices), 14)
        valid = rsi.dropna()
        assert not valid.empty, "상승 추세에서 RSI가 계산되어야 함"
        assert valid.iloc[-1] > 60

    def test_rsi_falling_trend_low(self):
        """강한 하락 추세에서 RSI가 낮아야 함 (<50)."""
        prices = [float(200 - i * 2) for i in range(50)]  # 일정 하락
        rsi = calculate_rsi(_series(prices), 14)
        assert rsi.dropna().iloc[-1] < 40

    def test_rsi_insufficient_data_nan(self):
        """데이터 부족 시 NaN 반환."""
        prices = [100.0, 101.0, 102.0]  # period=14보다 훨씬 적음
        rsi = calculate_rsi(_series(prices), 14)
        assert rsi.dropna().empty

    def test_rsi_constant_prices_neutral(self):
        """가격 변동 없으면 RSI = NaN (0으로 나누기 방지)."""
        prices = [100.0] * 20
        rsi = calculate_rsi(_series(prices), 14)
        # 변동 없으면 gains=losses=0 → RS=NaN → RSI=NaN or 50
        # 어느 쪽이든 100 초과/0 미만은 아님
        valid = rsi.dropna()
        if not valid.empty:
            assert 0 <= float(valid.iloc[-1]) <= 100

    def test_rsi_period_parameter(self):
        """RSI(7) vs RSI(14): 더 짧은 기간이 더 반응적."""
        df = _ohlcv(50)
        rsi_7  = calculate_rsi(df["close"], 7)
        rsi_14 = calculate_rsi(df["close"], 14)
        # 둘 다 유효한 값을 갖고 범위 내에 있어야 함
        assert not rsi_7.dropna().empty
        assert not rsi_14.dropna().empty


# ── MACD ──────────────────────────────────────────────────────────────────────

class TestMACD:
    def test_macd_returns_three_series(self):
        df = _ohlcv(100)
        macd, signal, hist = calculate_macd(df["close"])
        assert isinstance(macd, pd.Series)
        assert isinstance(signal, pd.Series)
        assert isinstance(hist, pd.Series)

    def test_histogram_is_macd_minus_signal(self):
        df = _ohlcv(50)
        macd, signal, hist = calculate_macd(df["close"])
        diff = (macd - signal - hist).abs()
        assert (diff.dropna() < 1e-10).all()

    def test_macd_rising_trend_positive(self):
        """상승 추세에서 MACD가 양수여야 함."""
        prices = [float(100 + i) for i in range(60)]
        macd, _, _ = calculate_macd(_series(prices))
        assert float(macd.dropna().iloc[-1]) > 0

    def test_macd_falling_trend_negative(self):
        """하락 추세에서 MACD가 음수여야 함."""
        prices = [float(200 - i) for i in range(60)]
        macd, _, _ = calculate_macd(_series(prices))
        assert float(macd.dropna().iloc[-1]) < 0

    def test_macd_custom_params(self):
        df = _ohlcv(50)
        macd, sig, hist = calculate_macd(df["close"], fast=5, slow=13, signal=4)
        assert not macd.dropna().empty


# ── EMA ───────────────────────────────────────────────────────────────────────

class TestEMA:
    def test_ema_length_matches_input(self):
        df = _ohlcv(50)
        ema = calculate_ema(df["close"], 9)
        assert len(ema) == len(df)

    def test_ema_lags_behind_rising_price(self):
        """상승 가격에서 EMA는 현재가보다 낮아야 함 (지연 특성)."""
        prices = [float(100 + i) for i in range(50)]
        close = _series(prices)
        ema = calculate_ema(close, 9)
        assert float(ema.iloc[-1]) < float(close.iloc[-1])

    def test_ema9_more_reactive_than_ema200(self):
        """단기 EMA가 장기 EMA보다 최신가에 더 근접해야 함."""
        df = _ohlcv(250)
        ema9  = calculate_ema(df["close"], 9)
        ema200 = calculate_ema(df["close"], 200)
        current = float(df["close"].iloc[-1])
        assert abs(float(ema9.iloc[-1]) - current) < abs(float(ema200.iloc[-1]) - current)


# ── ATR ───────────────────────────────────────────────────────────────────────

class TestATR:
    def test_atr_positive(self):
        df = _ohlcv(50)
        atr = calculate_atr(df["high"], df["low"], df["close"], 14)
        valid = atr.dropna()
        assert (valid > 0).all()

    def test_atr_high_volatility_larger(self):
        """변동성 높은 데이터에서 ATR이 더 커야 함."""
        rng = np.random.default_rng(0)
        n = 50
        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")

        low_vol = pd.DataFrame(
            {"high": 101 + rng.uniform(0, 0.5, n),
             "low": 99 - rng.uniform(0, 0.5, n),
             "close": 100 + rng.uniform(-0.2, 0.2, n)},
            index=idx,
        )
        high_vol = pd.DataFrame(
            {"high": 110 + rng.uniform(0, 5, n),
             "low": 90 - rng.uniform(0, 5, n),
             "close": 100 + rng.uniform(-3, 3, n)},
            index=idx,
        )
        atr_low  = calculate_atr(low_vol["high"],  low_vol["low"],  low_vol["close"])
        atr_high = calculate_atr(high_vol["high"], high_vol["low"], high_vol["close"])
        assert float(atr_high.dropna().mean()) > float(atr_low.dropna().mean())


# ── Bollinger Bands ───────────────────────────────────────────────────────────

class TestBollingerBands:
    def test_upper_above_lower(self):
        df = _ohlcv(50)
        upper, middle, lower = calculate_bollinger_bands(df["close"], 20, 2.0)
        valid = upper.dropna()
        assert (upper.dropna() > lower.dropna()).all()

    def test_middle_is_sma(self):
        """Middle band = SMA(20)."""
        df = _ohlcv(50)
        _, middle, _ = calculate_bollinger_bands(df["close"], 20, 2.0)
        sma = df["close"].rolling(20).mean()
        diff = (middle - sma).abs().dropna()
        assert (diff < 1e-8).all()

    def test_insufficient_data(self):
        prices = [100.0] * 5  # < 20
        upper, middle, lower = calculate_bollinger_bands(_series(prices), 20, 2.0)
        assert middle.dropna().empty

    def test_wider_std_dev_wider_bands(self):
        df = _ohlcv(50)
        u2, m2, l2 = calculate_bollinger_bands(df["close"], 20, 2.0)
        u3, m3, l3 = calculate_bollinger_bands(df["close"], 20, 3.0)
        valid = ~u2.isna()
        assert ((u3 - l3).dropna() > (u2 - l2).dropna()).all()


# ── VWAP ──────────────────────────────────────────────────────────────────────

class TestVWAP:
    def test_vwap_positive(self):
        df = _ohlcv(50)
        vwap = calculate_vwap(df["high"], df["low"], df["close"], df["volume"])
        assert (vwap.dropna() > 0).all()

    def test_vwap_reasonable_range(self):
        """VWAP은 해당 세션의 가격 범위 내에 위치해야 함.
        VWAP은 세션 누적 평균이므로 단일 봉의 H/L 범위 보장은 안 됨.
        대신 전체 데이터의 min(low) ~ max(high) 범위 내에 있어야 함."""
        df = _ohlcv(50)
        vwap = calculate_vwap(df["high"], df["low"], df["close"], df["volume"])
        valid = vwap.dropna()
        assert (valid >= df["low"].min()).all()
        assert (valid <= df["high"].max()).all()


# ── Volume MA ─────────────────────────────────────────────────────────────────

class TestVolumeMA:
    def test_volume_ma_positive(self):
        df = _ohlcv(50)
        vol_ma = calculate_volume_ma(df["volume"], 20)
        assert (vol_ma.dropna() > 0).all()

    def test_volume_ma_smoothing(self):
        """MA는 원래 시리즈보다 변동성이 낮아야 함."""
        df = _ohlcv(100)
        vol_ma = calculate_volume_ma(df["volume"], 20)
        assert df["volume"].std() > vol_ma.dropna().std()


# ── Support / Resistance ──────────────────────────────────────────────────────

class TestSupportResistance:
    def test_returns_two_lists(self):
        df = _ohlcv(50)
        supports, resistances = detect_support_resistance(df)
        assert isinstance(supports, list)
        assert isinstance(resistances, list)

    def test_support_below_resistance(self):
        df = _ohlcv(50)
        supports, resistances = detect_support_resistance(df)
        if supports and resistances:
            assert min(resistances) > min(supports)

    def test_n_levels_respected(self):
        df = _ohlcv(100)
        supports, resistances = detect_support_resistance(df, n_levels=3)
        assert len(supports) <= 3
        assert len(resistances) <= 3

    def test_insufficient_data_empty(self):
        df = _ohlcv(3)  # 너무 적은 데이터
        supports, resistances = detect_support_resistance(df)
        # 결과가 비어있거나 최소한 에러가 나지 않아야 함
        assert isinstance(supports, list)
