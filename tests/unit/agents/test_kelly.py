"""
Kelly Criterion 수학적 정확성 단위 테스트.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.risk.kelly import (
    calculate_kelly,
    kelly_growth_rate,
    recommended_kelly_fraction,
)
from agents.risk.sizing_models import TradeStatistics


def _stats(
    total: int,
    wins: int,
    avg_win: str,
    avg_loss: str,
) -> TradeStatistics:
    w = wins
    l = total - wins
    return TradeStatistics(
        total_trades=total,
        winning_trades=w,
        losing_trades=l,
        total_pnl=Decimal("0"),
        avg_win_usdt=Decimal(avg_win),
        avg_loss_usdt=Decimal(avg_loss),
        gross_win_usdt=Decimal(avg_win) * w,
        gross_loss_usdt=Decimal(avg_loss) * l,
    )


class TestKellyFormula:
    def test_textbook_example(self) -> None:
        """
        교과서 예시 검증:
        승률 60%, 평균 수익/손실 비율 2.0
        Full Kelly = (0.6 × 2.0 - 0.4) / 2.0 = 0.40 (40%)
        """
        stats = _stats(100, 60, "200", "100")  # avg_odds = 2.0
        result = calculate_kelly(stats, kelly_fraction=1.0, min_sample_size=10)

        assert result.is_valid is True
        assert abs(result.full_kelly_fraction - 0.40) < 0.01

    def test_quarter_kelly_applied(self) -> None:
        """Quarter-Kelly = Full Kelly × 0.25."""
        stats = _stats(100, 60, "200", "100")
        result = calculate_kelly(stats, kelly_fraction=0.25, min_sample_size=10)

        expected_full = 0.40
        expected_applied = min(0.05, expected_full * 0.25)  # cap at 5%
        assert abs(result.applied_fraction - expected_applied) < 0.01

    def test_negative_expected_value(self) -> None:
        """기대값 음수 (나쁜 전략) → Kelly 음수 → is_valid=False."""
        stats = _stats(100, 20, "100", "200")  # win_rate=0.2, odds=0.5
        result = calculate_kelly(stats, kelly_fraction=0.25, min_sample_size=10)

        assert result.is_valid is False
        assert result.full_kelly_fraction < 0
        assert "음수" in (result.reason or "")

    def test_insufficient_sample_size(self) -> None:
        """샘플 부족 → is_valid=False, fallback 적용."""
        stats = _stats(5, 3, "200", "100")
        result = calculate_kelly(
            stats,
            kelly_fraction=0.25,
            min_sample_size=20,
            fallback_risk_pct=0.01,
        )

        assert result.is_valid is False
        assert "샘플" in (result.reason or "")
        assert abs(result.applied_fraction - 0.01) < 1e-9

    def test_zero_avg_loss(self) -> None:
        """avg_loss=0 → 계산 불가 → fallback."""
        stats = _stats(100, 100, "200", "0")
        result = calculate_kelly(stats, kelly_fraction=0.25, min_sample_size=10)

        assert result.is_valid is False

    def test_very_high_win_rate(self) -> None:
        """높은 승률 → Kelly > 5% → 5%로 클리핑."""
        stats = _stats(200, 180, "500", "100")  # win_rate=0.9, odds=5.0
        result = calculate_kelly(stats, kelly_fraction=1.0, min_sample_size=20)

        # 5% 상한 적용 확인
        assert result.applied_fraction <= 0.05 + 1e-9
        assert result.full_kelly_fraction > 0.05

    def test_half_kelly_vs_quarter_kelly(self) -> None:
        """Half Kelly는 Quarter Kelly보다 2배 리스크."""
        stats = _stats(100, 60, "200", "100")
        quarter = calculate_kelly(stats, kelly_fraction=0.25, min_sample_size=10)
        half = calculate_kelly(stats, kelly_fraction=0.50, min_sample_size=10)

        # Quarter-Kelly applied 상한 5% 미만이면 2배 관계
        if quarter.applied_fraction < 0.025:
            assert abs(half.applied_fraction - quarter.applied_fraction * 2) < 0.001

    def test_kelly_fraction_is_conservative_by_default(self) -> None:
        """기본 Quarter-Kelly는 Full Kelly보다 항상 작거나 같다."""
        stats = _stats(100, 60, "200", "100")
        result = calculate_kelly(stats, kelly_fraction=0.25, min_sample_size=10)

        assert result.applied_fraction <= result.full_kelly_fraction + 1e-9


class TestTradeStatistics:
    def test_win_rate_calculation(self) -> None:
        stats = _stats(100, 65, "200", "100")
        assert stats.win_rate == pytest.approx(0.65)

    def test_loss_rate_calculation(self) -> None:
        stats = _stats(100, 65, "200", "100")
        assert stats.loss_rate == pytest.approx(0.35)

    def test_avg_odds_calculation(self) -> None:
        """avg_odds = avg_win / avg_loss = 200 / 100 = 2.0"""
        stats = _stats(100, 60, "200", "100")
        assert stats.avg_odds == pytest.approx(2.0)

    def test_profit_factor(self) -> None:
        """profit_factor = gross_win / gross_loss"""
        stats = _stats(100, 60, "200", "100")
        # gross_win = 200 × 60 = 12000, gross_loss = 100 × 40 = 4000
        assert stats.profit_factor == pytest.approx(12000 / 4000)

    def test_is_sufficient_true(self) -> None:
        stats = _stats(30, 20, "200", "100")
        assert stats.is_sufficient is True

    def test_is_sufficient_false_zero_trades(self) -> None:
        stats = _stats(0, 0, "0", "0")
        assert stats.is_sufficient is False


class TestKellyGrowthRate:
    def test_positive_growth_good_strategy(self) -> None:
        g = kelly_growth_rate(win_rate=0.60, avg_odds=2.0, kelly_fraction=0.25)
        assert g > 0

    def test_negative_growth_bad_strategy(self) -> None:
        g = kelly_growth_rate(win_rate=0.20, avg_odds=0.5, kelly_fraction=0.5)
        assert g < 0 or g == float("-inf")


class TestRecommendedKellyFraction:
    def test_very_few_trades(self) -> None:
        fraction = recommended_kelly_fraction(5, 0.6, 2.0)
        assert fraction == 0.0    # fallback 사용

    def test_small_sample(self) -> None:
        fraction = recommended_kelly_fraction(30, 0.6, 2.0)
        assert fraction == 0.125  # Eighth-Kelly

    def test_medium_sample(self) -> None:
        fraction = recommended_kelly_fraction(75, 0.6, 2.0)
        assert fraction == 0.25   # Quarter-Kelly

    def test_large_sample(self) -> None:
        fraction = recommended_kelly_fraction(150, 0.6, 2.0)
        assert fraction == 0.5    # Half-Kelly

    def test_capped_at_half_kelly(self) -> None:
        """아무리 많은 샘플도 Half-Kelly가 최대."""
        fraction = recommended_kelly_fraction(10000, 0.6, 2.0)
        assert fraction <= 0.5


class TestKellyCappedRiskPct:
    def test_capped_within_bounds(self) -> None:
        from agents.risk.kelly import KellyResult
        from agents.risk.constants import RISK_PER_TRADE_MIN, RISK_PER_TRADE_MAX

        result = KellyResult(
            full_kelly_fraction=0.40,
            applied_fraction=0.10,  # 10% > 5% 상한
            kelly_multiplier=0.25,
            win_rate=0.60,
            avg_odds=2.0,
            sample_size=100,
            is_valid=True,
        )
        assert result.capped_risk_pct <= RISK_PER_TRADE_MAX
        assert result.capped_risk_pct >= RISK_PER_TRADE_MIN

    def test_low_kelly_gets_min_risk(self) -> None:
        from agents.risk.kelly import KellyResult
        from agents.risk.constants import RISK_PER_TRADE_MIN

        result = KellyResult(
            full_kelly_fraction=0.001,
            applied_fraction=0.001,   # < 0.5% 하한
            kelly_multiplier=0.25,
            win_rate=0.50,
            avg_odds=1.1,
            sample_size=100,
            is_valid=True,
        )
        assert result.capped_risk_pct >= RISK_PER_TRADE_MIN
