"""
Chart signal scoring 단위 테스트.

검증 항목:
  - TREND_UP 풀백은 long_score 우위
  - TREND_DOWN은 short_score 또는 no_trade_score 우위
  - HIGH_VOLATILITY는 risk_score / no_trade_score 증가
  - 지표 충돌은 no_trade_score 증가
  - 모든 점수는 0~100 범위 유지
"""
from __future__ import annotations

import pytest

from agents.decision.chart_signals import score_chart_signals
from agents.decision.models import MarketRegime, SignalScore
from tests.unit.agents._strategy_fixtures import make_ta_result, make_tf_analysis


PRICE = 100_000.0
COIN = "BTC"
SYMBOL = "BTCUSDT"


def _ta(
    *,
    close: float = PRICE,
    rsi: float = 50.0,
    macd_hist: float = 0.0,
    macd_cross: str = "neutral",
    ema_align: str = "mixed",
    pct_b: float = 0.5,
    volume_ratio: float = 1.0,
    support: float = 99_500.0,
    resistance: float = 100_500.0,
) -> object:
    if ema_align == "bullish":
        ema9, ema21, ema50, ema200 = 103_000.0, 102_000.0, 99_000.0, 95_000.0
    elif ema_align == "bearish":
        ema9, ema21, ema50, ema200 = 97_000.0, 98_000.0, 101_000.0, 105_000.0
    else:
        ema9, ema21, ema50, ema200 = 100_000.0, 99_500.0, 100_500.0, 99_000.0

    bb_lower = 98_000.0
    bb_upper = 102_000.0
    bb_middle = 100_000.0

    tf = make_tf_analysis(
        close=close,
        rsi=rsi,
        macd_hist=macd_hist,
        macd_cross=macd_cross,
        ema9=ema9,
        ema21=ema21,
        ema50=ema50,
        ema200=ema200,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        pct_b=pct_b,
        volume_ratio=volume_ratio,
        symbol=SYMBOL,
        timeframe="1h",
    )
    return make_ta_result(
        COIN,
        SYMBOL,
        analyses={"1h": tf},
        support_levels=[support],
        resistance_levels=[resistance],
        latest_close=close,
    )


def _market(price_change: float = 0.0) -> dict:
    return {
        "current_price": PRICE,
        "recent_price_change_pct": price_change,
    }


def _scores(score: SignalScore) -> list[float]:
    return [
        score.long_score,
        score.short_score,
        score.no_trade_score,
        score.risk_score,
    ]


def test_trend_up_pullback_gives_higher_long_score() -> None:
    ta = _ta(
        rsi=38.0,
        macd_hist=1.0,
        macd_cross="bullish",
        ema_align="bullish",
        pct_b=0.22,
        volume_ratio=1.4,
        support=99_700.0,
        resistance=104_000.0,
    )

    result = score_chart_signals(MarketRegime.TREND_UP, ta, _market(price_change=0.3))

    assert result.long_score > result.short_score
    assert result.long_score > result.no_trade_score


def test_trend_down_gives_higher_short_score_or_no_trade_score() -> None:
    ta = _ta(
        rsi=62.0,
        macd_hist=-1.0,
        macd_cross="bearish",
        ema_align="bearish",
        pct_b=0.78,
        volume_ratio=1.2,
        support=96_000.0,
        resistance=100_300.0,
    )

    result = score_chart_signals(MarketRegime.TREND_DOWN, ta, _market(price_change=-0.2))

    assert result.short_score >= result.long_score
    assert max(result.short_score, result.no_trade_score) >= result.long_score


def test_high_volatility_increases_risk_score_and_no_trade_score() -> None:
    ta = _ta(
        rsi=38.0,
        macd_hist=1.0,
        macd_cross="bullish",
        ema_align="bullish",
        pct_b=0.22,
        volume_ratio=2.2,
        support=99_700.0,
        resistance=104_000.0,
    )

    normal = score_chart_signals(MarketRegime.TREND_UP, ta, _market(price_change=0.5))
    high_vol = score_chart_signals(MarketRegime.HIGH_VOLATILITY, ta, _market(price_change=0.5))

    assert high_vol.risk_score > normal.risk_score
    assert high_vol.no_trade_score > normal.no_trade_score


def test_conflicting_indicators_increase_no_trade_score() -> None:
    aligned = score_chart_signals(
        MarketRegime.TREND_UP,
        _ta(
            rsi=38.0,
            macd_hist=1.0,
            macd_cross="bullish",
            ema_align="bullish",
            pct_b=0.22,
            support=99_700.0,
            resistance=104_000.0,
        ),
        _market(price_change=0.2),
    )
    conflicting = score_chart_signals(
        MarketRegime.TREND_UP,
        _ta(
            rsi=72.0,
            macd_hist=-1.0,
            macd_cross="bearish",
            ema_align="bullish",
            pct_b=0.82,
            support=96_000.0,
            resistance=100_300.0,
        ),
        _market(price_change=0.2),
    )

    assert conflicting.no_trade_score > aligned.no_trade_score


@pytest.mark.parametrize(
    "regime,ta",
    [
        (MarketRegime.TREND_UP, _ta(rsi=30.0, macd_hist=1.0, ema_align="bullish", pct_b=0.1)),
        (MarketRegime.TREND_DOWN, _ta(rsi=75.0, macd_hist=-1.0, ema_align="bearish", pct_b=0.9)),
        (MarketRegime.RANGE, _ta(rsi=28.0, ema_align="mixed", pct_b=0.1)),
        (MarketRegime.HIGH_VOLATILITY, _ta(volume_ratio=3.0)),
        (MarketRegime.NEWS_EVENT, _ta(volume_ratio=3.0)),
        (MarketRegime.UNKNOWN, _ta()),
    ],
)
def test_scores_stay_between_0_and_100(regime: MarketRegime, ta: object) -> None:
    result = score_chart_signals(regime, ta, _market())

    assert all(0.0 <= value <= 100.0 for value in _scores(result))
    assert result.reasons
