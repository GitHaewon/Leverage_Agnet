"""
Scorer 단위 테스트 — 점수 변환 함수 정확성 검증.
"""
from __future__ import annotations

import pytest

from agents.technical_analysis.scorer import (
    INDICATOR_WEIGHTS,
    TIMEFRAME_WEIGHTS,
    aggregate_timeframe_scores,
    calculate_timeframe_score,
    calculate_trend_score,
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


# ── RSI 점수 ──────────────────────────────────────────────────────────────────

class TestScoreRSI:
    @pytest.mark.parametrize("rsi,expected", [
        (15,  +1.0),   # 극단 과매도
        (25,  +0.7),   # 과매도
        (35,  +0.3),   # 약한 매수
        (50,   0.0),   # 중립
        (65,  -0.3),   # 약한 매도
        (75,  -0.7),   # 과매수
        (85,  -1.0),   # 극단 과매수
    ])
    def test_rsi_to_score(self, rsi, expected):
        assert score_rsi(rsi) == expected

    def test_exact_boundary_30(self):
        assert score_rsi(30) == +0.7

    def test_exact_boundary_70(self):
        assert score_rsi(70) == -0.3

    def test_range_always_in_bounds(self):
        for rsi in range(0, 101):
            s = score_rsi(rsi)
            assert -1.0 <= s <= 1.0


# ── MACD 점수 ─────────────────────────────────────────────────────────────────

class TestScoreMACD:
    def test_bullish_cross(self):
        """음 → 양 전환: 강한 매수."""
        assert score_macd(0.1, -0.1) == +0.9

    def test_bearish_cross(self):
        """양 → 음 전환: 강한 매도."""
        assert score_macd(-0.1, 0.1) == -0.9

    def test_positive_histogram_bullish(self):
        assert score_macd(0.5, 0.3) == +0.3

    def test_negative_histogram_bearish(self):
        assert score_macd(-0.5, -0.3) == -0.3

    def test_zero_neutral(self):
        assert score_macd(0.0, 0.0) == 0.0


# ── EMA 정렬 점수 ──────────────────────────────────────────────────────────────

class TestScoreEMAAlignment:
    def test_full_bullish(self):
        """ema9 > ema21 > ema50 > ema200."""
        assert score_ema_alignment(200, 150, 100, 80) == +1.0

    def test_full_bearish(self):
        """ema9 < ema21 < ema50 < ema200."""
        assert score_ema_alignment(80, 100, 150, 200) == -1.0

    def test_above_200_weak_bullish(self):
        """ema9만 ema200 위 (혼재)."""
        score = score_ema_alignment(210, 100, 95, 200)
        assert score > 0

    def test_below_200_weak_bearish(self):
        score = score_ema_alignment(190, 200, 250, 300)
        assert score < 0

    def test_score_in_bounds(self):
        for ema9 in [80, 100, 120]:
            for ema21 in [90, 100, 110]:
                for ema50 in [95, 100, 105]:
                    s = score_ema_alignment(ema9, ema21, ema50, 100)
                    assert -1.0 <= s <= 1.0


# ── Bollinger Band 점수 ───────────────────────────────────────────────────────

class TestScoreBollinger:
    def test_extreme_lower_bullish(self):
        """하단 밴드 돌파 → 강한 매수."""
        # %B = (close - lower) / (upper - lower) ≈ 0
        assert score_bollinger(99.0, 110.0, 99.0, 104.5) == +1.0

    def test_extreme_upper_bearish(self):
        """상단 밴드 돌파 → 강한 매도."""
        assert score_bollinger(111.0, 110.0, 99.0, 104.5) == -1.0

    def test_lower_quarter_mildly_bullish(self):
        # lower=100, upper=120, close=103 → %B = 0.15 (≤0.20)
        score = score_bollinger(103, 120, 100, 110)
        assert score > 0

    def test_upper_quarter_mildly_bearish(self):
        # lower=100, upper=120, close=117 → %B = 0.85 (≥0.80)
        score = score_bollinger(117, 120, 100, 110)
        assert score < 0

    def test_middle_neutral(self):
        score = score_bollinger(110, 120, 100, 110)
        assert score == 0.0

    def test_zero_bandwidth_neutral(self):
        assert score_bollinger(100, 100, 100, 100) == 0.0


# ── Volume 점수 ───────────────────────────────────────────────────────────────

class TestScoreVolume:
    @pytest.mark.parametrize("vol_ratio,expected_positive", [
        (3.0, True),
        (2.0, True),
        (1.5, True),
        (1.0, True),
        (0.5, False),
    ])
    def test_volume_score_direction(self, vol_ratio, expected_positive):
        score = score_volume(vol_ratio * 1000, 1000)
        if expected_positive:
            assert score >= 0
        else:
            assert score < 0

    def test_zero_ma_returns_zero(self):
        assert score_volume(1000, 0) == 0.0


# ── 범주별 점수 집계 ──────────────────────────────────────────────────────────

class TestCalculateTimeframeScore:
    def test_all_positive_components(self):
        score = calculate_timeframe_score(0.8, 0.7, 0.6, 0.4)
        assert score > 0

    def test_all_negative_components(self):
        score = calculate_timeframe_score(-0.8, -0.7, -0.6, -0.2)
        assert score < 0

    def test_mixed_components(self):
        score = calculate_timeframe_score(0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_score_clamped_to_range(self):
        score = calculate_timeframe_score(1.0, 1.0, 1.0, 1.0)
        assert -1.0 <= score <= 1.0

    def test_weights_sum_to_one(self):
        total = sum(INDICATOR_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-10


# ── 타임프레임 가중 평균 ──────────────────────────────────────────────────────

class TestAggregateTimeframeScores:
    def test_all_timeframes_present(self):
        scores = {
            "1d": 0.8,
            "4h": 0.6,
            "1h": 0.4,
            "15m": 0.2,
            "5m": 0.1,
            "1m": 0.0,
        }
        result = aggregate_timeframe_scores(scores)
        # 가중 평균이므로 1d(0.30)의 영향이 큼
        assert result > 0.3  # 1d 가중치 0.30 × 0.8 = 0.24가 크게 작용
        assert -1.0 <= result <= 1.0

    def test_empty_scores(self):
        assert aggregate_timeframe_scores({}) == 0.0

    def test_single_timeframe(self):
        result = aggregate_timeframe_scores({"1d": 0.8})
        assert abs(result - 0.8) < 1e-10

    def test_unknown_timeframe_zero_weight(self):
        result = aggregate_timeframe_scores({"unknown": 1.0})
        assert result == 0.0

    def test_partial_timeframes(self):
        """일부 타임프레임만 있을 때도 정상 동작."""
        result = aggregate_timeframe_scores({"1h": 0.5, "4h": 0.5})
        # 1h(0.20) + 4h(0.25) 가중 평균 = 0.5
        assert abs(result - 0.5) < 1e-10

    def test_timeframe_weights_sum(self):
        total = sum(TIMEFRAME_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-10


# ── Signal 결정 ───────────────────────────────────────────────────────────────

class TestScoreToSignal:
    def test_bullish(self):
        assert score_to_signal(0.5) == "BULLISH"
        assert score_to_signal(0.2) == "BULLISH"

    def test_bearish(self):
        assert score_to_signal(-0.5) == "BEARISH"
        assert score_to_signal(-0.2) == "BEARISH"

    def test_neutral(self):
        assert score_to_signal(0.0) == "NEUTRAL"
        assert score_to_signal(0.1) == "NEUTRAL"
        assert score_to_signal(-0.1) == "NEUTRAL"

    def test_exact_boundaries(self):
        assert score_to_signal(0.20) == "BULLISH"
        assert score_to_signal(-0.20) == "BEARISH"
        assert score_to_signal(0.19) == "NEUTRAL"


# ── 복합 결정 함수 ────────────────────────────────────────────────────────────

class TestDetermineHelpers:
    def test_macd_cross_bullish(self):
        assert determine_macd_cross(0.1, -0.1) == "bullish"

    def test_macd_cross_bearish(self):
        assert determine_macd_cross(-0.1, 0.1) == "bearish"

    def test_macd_cross_neutral_positive(self):
        assert determine_macd_cross(0.1, 0.05) == "neutral"

    def test_ema_alignment_bullish(self):
        assert determine_ema_alignment(200, 150, 100, 80) == "bullish"

    def test_ema_alignment_bearish(self):
        assert determine_ema_alignment(80, 100, 150, 200) == "bearish"

    def test_ema_alignment_mixed(self):
        assert determine_ema_alignment(120, 100, 110, 90) == "mixed"

    def test_bb_position_upper(self):
        # %B = 0.9 → upper_third
        assert determine_bb_position(119, 120, 100) == "upper_third"

    def test_bb_position_lower(self):
        # %B = 0.1 → lower_third
        assert determine_bb_position(102, 120, 100) == "lower_third"

    def test_bb_position_middle(self):
        # %B = 0.5 → middle
        assert determine_bb_position(110, 120, 100) == "middle"

    def test_bb_position_zero_bandwidth(self):
        assert determine_bb_position(100, 100, 100) == "middle"
