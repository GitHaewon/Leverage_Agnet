"""
Market Structure 순수 점수 계산 함수.

AGENTS.md §4.4 기준.
"""
from __future__ import annotations

from typing import Literal

from agents.market_structure.models import MARKET_STRUCTURE_WEIGHTS


def score_funding_rate(rate: float) -> float:
    """Funding Rate → 점수 (역발상 지표).

    극단적 양수 Funding = 롱 과다 = 숏 신호 → 음수 점수
    극단적 음수 Funding = 숏 과다 = 롱 신호 → 양수 점수
    """
    if rate >= 0.003:    return -1.0
    if rate >= 0.001:    return -0.6
    if rate >= 0.0001:   return -0.2
    if rate >= -0.0001:  return  0.0
    if rate >= -0.001:   return +0.2
    if rate >= -0.003:   return +0.6
    return +1.0


def score_oi_change(oi_change_pct: float, price_change_pct: float) -> float:
    """OI 변화율 + 가격 방향 조합으로 포지션 추세를 판단한다.

    OI 증가 + 가격 상승 = 신규 롱 진입 (강세)
    OI 증가 + 가격 하락 = 신규 숏 진입 (약세)
    OI 감소 = 포지션 청산 (방향 불분명)
    """
    if oi_change_pct > 2 and price_change_pct > 0:
        return +0.8
    if oi_change_pct > 2 and price_change_pct < 0:
        return -0.8
    if oi_change_pct < -2:
        return 0.0
    # 소폭 변화: 비례 점수
    return max(-1.0, min(1.0, oi_change_pct * 0.2))


def score_long_short(ratio: float) -> float:
    """롱/숏 비율 → 역발상 점수.

    롱 과다(ratio > 1.5) = 숏 신호 → 음수
    숏 과다(ratio < 0.7) = 롱 신호 → 양수
    """
    if ratio >= 2.0:   return -1.0
    if ratio >= 1.5:   return -0.6
    if ratio >= 1.2:   return -0.2
    if ratio >= 0.8:   return  0.0
    if ratio >= 0.7:   return +0.2
    if ratio >= 0.5:   return +0.6
    return +1.0


def score_taker_ratio(ratio: float) -> float:
    """Taker 매수/매도 비율 → 점수.

    매수 우세(ratio > 1) = 매수 압력 = 양수
    매도 우세(ratio < 1) = 매도 압력 = 음수
    """
    if ratio >= 1.5:   return +1.0
    if ratio >= 1.2:   return +0.6
    if ratio >= 1.05:  return +0.2
    if ratio >= 0.95:  return  0.0
    if ratio >= 0.8:   return -0.2
    if ratio >= 0.6:   return -0.6
    return -1.0


def combine_market_scores(
    funding: float,
    oi: float,
    long_short: float,
    taker: float,
    weights: dict[str, float] = MARKET_STRUCTURE_WEIGHTS,
) -> float:
    combined = (
        funding * weights["funding_rate"]
        + oi * weights["oi_change"]
        + long_short * weights["long_short"]
        + taker * weights["taker_ratio"]
    )
    return max(-1.0, min(1.0, combined))


def determine_whale_activity(
    whale_volume_usdt: float,
    price_change_pct: float,
    threshold: float = 500_000.0,
) -> str:
    """고래 거래량과 가격 방향으로 고래 활동을 분류한다."""
    if whale_volume_usdt < threshold:
        return "neutral"
    return "accumulating" if price_change_pct >= 0 else "distributing"


def determine_market_regime(combined_score: float) -> str:
    """종합 점수로 시장 구조를 분류한다."""
    if combined_score >= 0.3:
        return "bullish_structure"
    if combined_score <= -0.3:
        return "bearish_structure"
    return "ranging"
