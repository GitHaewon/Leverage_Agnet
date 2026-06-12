"""
Derivatives market scoring 단위 테스트.

검증 항목:
  - 가격 상승 + OI 상승 + 중립 펀딩은 롱 소폭 우대
  - 고펀딩 + 롱 쏠림은 리스크 증가 및 crowded_side=LONG
  - 음수 펀딩 + 숏 쏠림은 리스크 증가 및 crowded_side=SHORT
  - 가격 급변 + OI 감소는 청산 이벤트 리스크 증가
  - 데이터 없음은 안전한 중립 결과
  - 모든 점수는 유효 범위 유지
"""
from __future__ import annotations

import pytest

from agents.decision.derivatives_market import score_derivatives_market
from agents.decision.models import DerivativesMarketScore, MarketRegime


def _derivatives(**overrides: float) -> dict:
    data = {
        "funding_rate": 0.0,
        "open_interest_change": 0.0,
        "long_short_ratio": 1.0,
        "long_account_ratio": 0.5,
        "short_account_ratio": 0.5,
    }
    data.update(overrides)
    return data


def _price(**overrides: float) -> dict:
    data = {
        "price_change": 0.0,
        "volume_change": 0.0,
    }
    data.update(overrides)
    return data


def _scores(score: DerivativesMarketScore) -> list[float]:
    return [
        score.long_score_adjustment,
        score.short_score_adjustment,
        score.risk_score,
    ]


def test_price_up_oi_up_neutral_funding_gives_modest_long_adjustment() -> None:
    result = score_derivatives_market(
        _derivatives(funding_rate=0.0001, open_interest_change=1.2),
        _price(price_change=0.8),
        MarketRegime.TREND_UP,
    )

    assert 0.0 < result.long_score_adjustment <= 10.0
    assert result.short_score_adjustment == 0.0
    assert result.crowded_side == "NONE"


def test_high_funding_long_crowding_increases_risk_and_sets_crowded_long() -> None:
    result = score_derivatives_market(
        _derivatives(
            funding_rate=0.0018,
            open_interest_change=2.0,
            long_short_ratio=1.8,
            long_account_ratio=0.66,
        ),
        _price(price_change=1.1),
        MarketRegime.TREND_UP,
    )

    assert result.crowded_side == "LONG"
    assert result.risk_score >= 40.0
    assert result.long_score_adjustment < 0.0


def test_negative_funding_short_crowding_increases_risk_and_sets_crowded_short() -> None:
    result = score_derivatives_market(
        _derivatives(
            funding_rate=-0.0016,
            open_interest_change=2.0,
            long_short_ratio=0.55,
            short_account_ratio=0.64,
        ),
        _price(price_change=-1.0),
        MarketRegime.TREND_DOWN,
    )

    assert result.crowded_side == "SHORT"
    assert result.risk_score >= 40.0
    assert result.short_score_adjustment < 0.0


def test_price_spike_oi_drop_increases_risk() -> None:
    calm = score_derivatives_market(
        _derivatives(funding_rate=0.0, open_interest_change=0.0),
        _price(price_change=0.2),
        MarketRegime.RANGE,
    )
    spike = score_derivatives_market(
        _derivatives(funding_rate=0.0, open_interest_change=-3.0),
        _price(price_change=2.8),
        MarketRegime.RANGE,
    )

    assert spike.risk_score > calm.risk_score
    assert any("청산 이벤트" in reason for reason in spike.reasons)


def test_missing_data_returns_neutral_safe_result() -> None:
    result = score_derivatives_market(
        None,
        _price(price_change=3.0),
        MarketRegime.HIGH_VOLATILITY,
    )

    assert result.long_score_adjustment == 0.0
    assert result.short_score_adjustment == 0.0
    assert result.risk_score == 0.0
    assert result.crowded_side == "NONE"
    assert result.reasons


@pytest.mark.parametrize(
    "derivatives,price,regime",
    [
        (
            _derivatives(
                funding_rate=0.01,
                open_interest_change=20.0,
                long_short_ratio=5.0,
                long_account_ratio=0.95,
                liquidation_usdt=100_000_000.0,
            ),
            _price(price_change=8.0, volume_change=300.0),
            MarketRegime.NEWS_EVENT,
        ),
        (
            _derivatives(
                funding_rate=-0.01,
                open_interest_change=20.0,
                long_short_ratio=0.1,
                short_account_ratio=0.95,
                liquidation_usdt=100_000_000.0,
            ),
            _price(price_change=-8.0, volume_change=300.0),
            MarketRegime.HIGH_VOLATILITY,
        ),
        (
            _derivatives(funding_rate=0.0, open_interest_change=-20.0),
            _price(price_change=10.0),
            MarketRegime.UNKNOWN,
        ),
    ],
)
def test_scores_stay_within_valid_ranges(
    derivatives: dict,
    price: dict,
    regime: MarketRegime,
) -> None:
    result = score_derivatives_market(derivatives, price, regime)

    assert -30.0 <= result.long_score_adjustment <= 30.0
    assert -30.0 <= result.short_score_adjustment <= 30.0
    assert 0.0 <= result.risk_score <= 100.0
    assert result.crowded_side in {"LONG", "SHORT", "NONE"}
    assert result.reasons
    assert all(-30.0 <= value <= 100.0 for value in _scores(result))
