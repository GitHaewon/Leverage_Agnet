"""
지표값 → 점수 변환 함수 모음.

각 함수는 -1.0 (강한 매도) ~ +1.0 (강한 매수) 점수를 반환한다.
모든 함수는 순수 함수 (stateless, side-effect 없음).

가중치 (AGENTS.md §2.4):
  범주:      trend=0.35 / momentum=0.30 / volatility=0.20 / volume=0.15
  타임프레임: 1d=0.30 / 4h=0.25 / 1h=0.20 / 15m=0.15 / 5m=0.07 / 1m=0.03
"""
from __future__ import annotations

from typing import Literal

# ── 범주 가중치 ───────────────────────────────────────────────────────────────

INDICATOR_WEIGHTS: dict[str, float] = {
    "trend":      0.35,  # EMA 배열, MACD 방향
    "momentum":   0.30,  # RSI
    "volatility": 0.20,  # Bollinger Bands, ATR
    "volume":     0.15,  # 거래량 비율
}

# ── 타임프레임 가중치 ─────────────────────────────────────────────────────────

TIMEFRAME_WEIGHTS: dict[str, float] = {
    "1d":  0.30,
    "4h":  0.25,
    "1h":  0.20,
    "15m": 0.15,
    "5m":  0.07,
    "1m":  0.03,
}

# ── Signal 임계값 ─────────────────────────────────────────────────────────────

BULLISH_THRESHOLD = 0.20
BEARISH_THRESHOLD = -0.20


# ── 개별 지표 점수 함수 ───────────────────────────────────────────────────────

def score_rsi(rsi: float) -> float:
    """RSI → 점수 (AGENTS.md §2.4 제공 함수)."""
    if rsi <= 20: return +1.0   # 극단 과매도
    if rsi <= 30: return +0.7   # 과매도
    if rsi <= 40: return +0.3   # 약한 매수
    if rsi <= 60: return  0.0   # 중립
    if rsi <= 70: return -0.3   # 약한 매도
    if rsi <= 80: return -0.7   # 과매수
    return -1.0                  # 극단 과매수


def score_macd(histogram: float, prev_histogram: float) -> float:
    """MACD 히스토그램 방향 + 크로스 시그널 → 점수."""
    if histogram > 0 and prev_histogram <= 0:   return +0.9  # 황금 크로스
    if histogram < 0 and prev_histogram >= 0:   return -0.9  # 죽음 크로스
    if histogram > 0:                            return +0.3  # 강세 지속
    if histogram < 0:                            return -0.3  # 약세 지속
    return 0.0


def score_ema_alignment(
    ema9: float,
    ema21: float,
    ema50: float,
    ema200: float,
) -> float:
    """EMA 정렬 → 트렌드 점수."""
    # 완전 정렬 (상승)
    if ema9 > ema21 > ema50 > ema200:   return +1.0
    # 단기 강세 + 장기 위
    if ema9 > ema21 and ema21 > ema200: return +0.6
    # 장기선 위 (약한 강세)
    if ema9 > ema200:                    return +0.3
    # 완전 정렬 (하락)
    if ema9 < ema21 < ema50 < ema200:   return -1.0
    # 단기 약세 + 장기 아래
    if ema9 < ema21 and ema21 < ema200: return -0.6
    # 장기선 아래 (약한 약세)
    if ema9 < ema200:                    return -0.3
    return 0.0


def score_bollinger(
    close: float,
    upper: float,
    lower: float,
    middle: float,
) -> float:
    """Bollinger Bands 위치 → 점수 (역발상: 극단 = 반전 신호)."""
    bandwidth = upper - lower
    if bandwidth <= 0:
        return 0.0

    # %B = (close - lower) / (upper - lower)
    pct_b = (close - lower) / bandwidth

    if pct_b <= 0.02:  return +1.0   # 극단 하단 돌파 (강한 과매도 반전)
    if pct_b <= 0.20:  return +0.5   # 하단 1/5 (매수 관심)
    if pct_b >= 0.98:  return -1.0   # 극단 상단 돌파 (강한 과매수 반전)
    if pct_b >= 0.80:  return -0.5   # 상단 1/5 (매도 관심)
    return 0.0


def score_volume(current_volume: float, ma20_volume: float) -> float:
    """
    거래량 비율 → 점수.

    거래량은 방향 중립이지만, 평균 이상 거래량은
    현재 추세를 확인하는 신호로 사용한다.
    (양수 = 추세 신뢰도 높음)
    """
    if ma20_volume <= 0:
        return 0.0
    ratio = current_volume / ma20_volume
    if ratio >= 3.0:  return +0.5
    if ratio >= 2.0:  return +0.4
    if ratio >= 1.5:  return +0.3
    if ratio >= 1.0:  return +0.1
    return -0.1  # 거래량 감소 = 약한 추세


# ── 범주별 점수 집계 ──────────────────────────────────────────────────────────

def calculate_trend_score(ema_score: float, macd_score: float) -> float:
    """추세 점수 = EMA 0.5 + MACD 0.5."""
    return ema_score * 0.5 + macd_score * 0.5


def calculate_momentum_score(rsi_score: float) -> float:
    """모멘텀 점수 (현재 RSI만 사용; Stochastic 추후 추가 가능)."""
    return rsi_score


def calculate_volatility_score(bb_score: float, atr: float, prev_atr: float) -> float:
    """
    변동성 점수 = BB 0.7 + ATR 방향 0.3.

    ATR 증가 = 추세 강화 (방향 중립이지만 BB 방향과 결합).
    """
    if prev_atr > 0:
        atr_change = (atr - prev_atr) / prev_atr
        atr_score = min(max(atr_change * 2, -0.5), 0.5)  # [-0.5, +0.5] 클리핑
    else:
        atr_score = 0.0

    return bb_score * 0.7 + atr_score * 0.3


def calculate_timeframe_score(
    trend_score: float,
    momentum_score: float,
    volatility_score: float,
    volume_score: float,
) -> float:
    """
    타임프레임 종합 점수 (AGENTS.md §2.4 가중치 적용).

    score = trend×0.35 + momentum×0.30 + volatility×0.20 + volume×0.15
    """
    score = (
        trend_score      * INDICATOR_WEIGHTS["trend"]
        + momentum_score * INDICATOR_WEIGHTS["momentum"]
        + volatility_score * INDICATOR_WEIGHTS["volatility"]
        + volume_score   * INDICATOR_WEIGHTS["volume"]
    )
    return max(-1.0, min(1.0, score))


def aggregate_timeframe_scores(
    scores: dict[str, float],
) -> float:
    """
    타임프레임별 점수를 가중 평균하여 최종 tech_score 계산.

    사용 가능한 타임프레임만 포함 (데이터 없는 TF는 제외).
    """
    total_weight = 0.0
    weighted_sum = 0.0

    for tf, score in scores.items():
        weight = TIMEFRAME_WEIGHTS.get(tf, 0.0)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    result = weighted_sum / total_weight
    return max(-1.0, min(1.0, result))


def score_to_signal(score: float) -> str:
    """점수 → 시그널 문자열."""
    if score >= BULLISH_THRESHOLD:
        return "BULLISH"
    if score <= BEARISH_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


def determine_macd_cross(
    histogram: float,
    prev_histogram: float,
) -> str:
    """MACD 크로스 방향 결정."""
    if histogram > 0 and prev_histogram <= 0:
        return "bullish"
    if histogram < 0 and prev_histogram >= 0:
        return "bearish"
    return "neutral"


def determine_ema_alignment(
    ema9: float,
    ema21: float,
    ema50: float,
    ema200: float,
) -> str:
    """EMA 정렬 상태 결정."""
    if ema9 > ema21 > ema50 > ema200:
        return "bullish"
    if ema9 < ema21 < ema50 < ema200:
        return "bearish"
    return "mixed"


def determine_bb_position(
    close: float,
    upper: float,
    lower: float,
) -> str:
    """Bollinger Band 위치 결정 (3등분)."""
    bandwidth = upper - lower
    if bandwidth <= 0:
        return "middle"
    pct_b = (close - lower) / bandwidth
    if pct_b >= 0.667:
        return "upper_third"
    if pct_b <= 0.333:
        return "lower_third"
    return "middle"
