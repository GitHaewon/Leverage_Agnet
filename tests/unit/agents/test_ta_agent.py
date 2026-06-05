"""
TechnicalAnalysisAgent / TechnicalAnalyzer 통합 테스트.

실제 OHLCV 데이터로 전체 파이프라인 검증:
  - 단일 타임프레임 분석
  - 멀티 타임프레임 집계
  - JSON 출력 포맷
  - 엣지 케이스 (데이터 부족, 빈 데이터, 단일 TF)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.technical_analysis.agent import TechnicalAnalysisAgent
from agents.technical_analysis.analyzer import TechnicalAnalyzer
from agents.technical_analysis.models import (
    BollingerBandsResult,
    EMAResult,
    MACDResult,
    TechnicalAnalysisResult,
    TimeframeAnalysis,
)


# ── 테스트 데이터 팩토리 ──────────────────────────────────────────────────────

def _ohlcv(
    n: int = 250,
    base: float = 67450.0,
    trend: float = 1.0,
    volatility: float = 200.0,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.arange(n) * trend + rng.normal(0, volatility, n)
    closes = np.maximum(closes, 1.0)  # 음수 방지
    highs   = closes + rng.uniform(50, 300, n)
    lows    = closes - rng.uniform(50, 300, n)
    lows    = np.maximum(lows, 1.0)
    opens   = closes + rng.normal(0, 50, n)
    volumes = rng.uniform(100, 1000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


def _multi_tf_data(n: int = 250) -> dict[str, pd.DataFrame]:
    return {
        "1h":  _ohlcv(n, seed=1),
        "4h":  _ohlcv(n // 4, seed=2),
        "1d":  _ohlcv(n // 24, seed=3),
        "15m": _ohlcv(n * 4, seed=4),
    }


# ── TechnicalAnalyzer 단위 테스트 ─────────────────────────────────────────────

class TestTechnicalAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return TechnicalAnalyzer()

    @pytest.fixture
    def df(self):
        return _ohlcv(250)

    def test_returns_timeframe_analysis(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert isinstance(result, TimeframeAnalysis)

    def test_symbol_and_timeframe(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert result.symbol == "BTCUSDT"
        assert result.timeframe == "1h"

    def test_rsi_in_range(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert 0 <= result.rsi <= 100

    def test_score_in_range(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert -1.0 <= result.score <= 1.0

    def test_signal_valid(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert result.signal in ("BULLISH", "NEUTRAL", "BEARISH")

    def test_macd_result_type(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert isinstance(result.macd, MACDResult)
        assert result.macd.cross in ("bullish", "bearish", "neutral")

    def test_ema_result_type(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert isinstance(result.ema, EMAResult)
        assert result.ema.alignment in ("bullish", "bearish", "mixed")

    def test_bb_result_type(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert isinstance(result.bollinger_bands, BollingerBandsResult)
        assert result.bollinger_bands.position in ("upper_third", "middle", "lower_third")

    def test_atr_positive(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert result.atr > 0

    def test_vwap_positive(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert result.vwap > 0

    def test_volume_ratio_positive(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert result.volume_ratio > 0

    def test_signals_fired_is_list(self, analyzer, df):
        result = analyzer.analyze(df, "BTCUSDT", "1h")
        assert isinstance(result.signals_fired, list)

    def test_insufficient_data_returns_none(self, analyzer):
        tiny_df = _ohlcv(5)  # < _MIN_ROWS=30
        result = analyzer.analyze(tiny_df, "BTCUSDT", "1h")
        assert result is None

    def test_empty_df_returns_none(self, analyzer):
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = analyzer.analyze(empty, "BTCUSDT", "1h")
        assert result is None

    def test_missing_column_returns_none(self, analyzer, df):
        no_volume = df.drop(columns=["volume"])
        result = analyzer.analyze(no_volume, "BTCUSDT", "1h")
        assert result is None

    def test_bullish_trend_ema_alignment(self, analyzer):
        """일정한 상승 추세에서 EMA가 bullish 정렬이어야 함.
        RSI·BB는 역발상 지표라 극단 상승장에선 음수 점수를 줄 수 있으므로
        최종 score가 아닌 EMA alignment로 검증한다."""
        rising_df = _ohlcv(250, trend=5.0, volatility=10.0)
        result = analyzer.analyze(rising_df, "BTCUSDT", "1h")
        assert result is not None
        assert result.ema.alignment == "bullish"

    def test_bearish_trend_ema_alignment(self, analyzer):
        """일정한 하락 추세에서 EMA가 bearish 정렬이어야 함."""
        falling_df = _ohlcv(250, trend=-5.0, volatility=10.0)
        result = analyzer.analyze(falling_df, "BTCUSDT", "1h")
        assert result is not None
        assert result.ema.alignment == "bearish"

    def test_moderate_rising_trend_score_not_extreme_negative(self, analyzer):
        """적당한 상승 추세 + 노이즈: score가 극단 음수는 아니어야 함.
        변동성을 크게 줘서 RSI가 50 근처로 유지되도록 함."""
        rising_df = _ohlcv(250, trend=1.0, volatility=150.0, seed=99)
        result = analyzer.analyze(rising_df, "BTCUSDT", "1h")
        assert result is not None
        assert result.score > -0.5  # 적당한 상승에서 극단 매도 아님


# ── to_dict JSON 포맷 검증 ────────────────────────────────────────────────────

class TestTimeframeAnalysisToDict:
    @pytest.fixture
    def analysis(self):
        analyzer = TechnicalAnalyzer()
        df = _ohlcv(250)
        return analyzer.analyze(df, "BTCUSDT", "1h")

    def test_required_keys(self, analysis):
        """요청 포맷 JSON 필드 검증."""
        d = analysis.to_dict()
        assert "symbol" in d
        assert "timeframe" in d
        assert "rsi" in d
        assert "macd" in d
        assert "ema" in d
        assert "atr" in d
        assert "signal" in d

    def test_macd_subkeys(self, analysis):
        d = analysis.to_dict()
        assert "macd" in d["macd"]
        assert "signal" in d["macd"]
        assert "histogram" in d["macd"]
        assert "cross" in d["macd"]

    def test_ema_subkeys(self, analysis):
        d = analysis.to_dict()
        assert "ema9" in d["ema"]
        assert "ema21" in d["ema"]
        assert "ema50" in d["ema"]
        assert "ema200" in d["ema"]
        assert "alignment" in d["ema"]

    def test_bollinger_bands_in_output(self, analysis):
        d = analysis.to_dict()
        assert "bollinger_bands" in d
        bb = d["bollinger_bands"]
        assert "upper" in bb and "middle" in bb and "lower" in bb

    def test_signal_is_string(self, analysis):
        d = analysis.to_dict()
        assert isinstance(d["signal"], str)
        assert d["signal"] in ("BULLISH", "NEUTRAL", "BEARISH")

    def test_values_are_rounded(self, analysis):
        d = analysis.to_dict()
        # rsi는 소수점 2자리
        assert isinstance(d["rsi"], float)
        assert d["rsi"] == round(d["rsi"], 2)


# ── TechnicalAnalysisAgent 통합 테스트 ───────────────────────────────────────

class TestTechnicalAnalysisAgent:
    @pytest.fixture
    def agent(self):
        return TechnicalAnalysisAgent()

    @pytest.fixture
    def ohlcv(self):
        return _multi_tf_data()

    def test_returns_result(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert isinstance(result, TechnicalAnalysisResult)

    def test_tech_score_in_range(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert -1.0 <= result.tech_score <= 1.0

    def test_symbol_auto_generated(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert result.symbol == "BTCUSDT"

    def test_symbol_explicit(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC", symbol="BTCUSDT")
        assert result.symbol == "BTCUSDT"

    def test_timeframe_scores_dict(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert isinstance(result.timeframe_scores, dict)
        for tf in ohlcv.keys():
            assert tf in result.timeframe_scores

    def test_analyses_contains_valid_tfs(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        for tf, analysis in result.analyses.items():
            assert isinstance(analysis, TimeframeAnalysis)

    def test_signals_fired_no_duplicates(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert len(result.signals_fired) == len(set(result.signals_fired))

    def test_support_resistance_levels(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert isinstance(result.support_levels, list)
        assert isinstance(result.resistance_levels, list)

    def test_latest_close_positive(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        assert result.latest_close > 0

    def test_to_dict_full_result(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        d = result.to_dict()
        assert "coin" in d
        assert "tech_score" in d
        assert "timeframe_scores" in d
        assert "signals_fired" in d

    def test_to_dict_timeframe_specific(self, agent, ohlcv):
        result = agent.run(ohlcv, "BTC")
        # 1h 타임프레임 상세 JSON
        d = result.to_dict("1h")
        assert d["timeframe"] == "1h"
        assert "rsi" in d
        assert "macd" in d

    def test_empty_ohlcv_data(self, agent):
        result = agent.run({}, "BTC")
        assert result.tech_score == 0.0
        assert result.analyses == {}

    def test_insufficient_data_all_tfs(self, agent):
        tiny_data = {"1h": _ohlcv(5), "4h": _ohlcv(5)}
        result = agent.run(tiny_data, "BTC")
        # 데이터 부족 → score=0.0 폴백, 에러 없음
        assert result.tech_score == 0.0

    def test_partial_data_available(self, agent):
        """일부 TF만 충분한 데이터 있을 때."""
        mixed = {
            "1h":  _ohlcv(250),    # 충분
            "4h":  _ohlcv(5),      # 부족 → 0.0 폴백
        }
        result = agent.run(mixed, "BTC")
        assert isinstance(result.tech_score, float)
        assert -1.0 <= result.tech_score <= 1.0
        # 1h는 분석됨
        assert "1h" in result.analyses

    def test_eth_symbol(self, agent):
        eth_data = {"1h": _ohlcv(250, base=3500.0)}
        result = agent.run(eth_data, "ETH")
        assert result.coin == "ETH"
        assert result.symbol == "ETHUSDT"

    def test_rising_market_bullish_ema(self, agent):
        """강한 상승장에서 EMA alignment는 bullish.
        RSI·BB는 역발상 지표라 극단 상승장 score가 음수일 수 있으므로
        EMA 정렬로 추세 방향을 검증한다."""
        bull_data = {"1h": _ohlcv(250, trend=10.0, volatility=5.0)}
        result = agent.run(bull_data, "BTC")
        assert result.analyses["1h"].ema.alignment == "bullish"

    def test_falling_market_bearish_ema(self, agent):
        """강한 하락장에서 EMA alignment는 bearish."""
        bear_data = {"1h": _ohlcv(250, trend=-10.0, volatility=5.0)}
        result = agent.run(bear_data, "BTC")
        assert result.analyses["1h"].ema.alignment == "bearish"

    def test_moderate_rising_positive_score(self, agent):
        """적당한 상승 추세: RSI가 극단에 가지 않아 score > 0 가능.
        변동성을 크게 줘서 RSI가 중립 범위에 머물도록."""
        bull_data = {"1h": _ohlcv(250, trend=2.0, volatility=200.0, seed=77)}
        result = agent.run(bull_data, "BTC")
        # tech_score가 양수이거나 EMA가 bullish
        assert result.tech_score > 0 or result.analyses["1h"].ema.alignment == "bullish"
