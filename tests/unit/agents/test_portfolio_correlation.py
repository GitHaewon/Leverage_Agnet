"""
Portfolio Correlation 테스트.

검증:
  - 빈 포지션 → adjusted = raw = 0
  - 단일 자산 → adjusted = raw (상관관계 없음)
  - BTC + ETH 동일 방향 → effective_rho = +0.85, adjusted < raw
  - BTC + ETH 반대 방향 → effective_rho = -0.85, adjusted << raw (헤지)
  - adjustment_factor 범위: 0 < factor ≤ 1
  - pairs 필드 검증
"""
from __future__ import annotations

import math
from decimal import Decimal

import pytest

from agents.portfolio.correlation import calculate_correlation_risk, _calc_2asset_risk
from agents.portfolio.models import BTC_ETH_CORRELATION

from tests.unit.agents._portfolio_fixtures import (
    make_account,
    make_btc_long,
    make_btc_short,
    make_eth_long,
    make_eth_short,
)


# ── 빈 포지션 ────────────────────────────────────────────────────────────────

def test_empty_positions_zero_risk():
    result = calculate_correlation_risk([])
    assert result.raw_risk_usdt == Decimal("0")
    assert result.adjusted_risk_usdt == Decimal("0")


def test_empty_positions_factor_is_one():
    result = calculate_correlation_risk([])
    assert result.adjustment_factor == 1.0


def test_empty_positions_no_pairs():
    result = calculate_correlation_risk([])
    assert result.pairs == []


# ── 단일 자산 (BTC만) ─────────────────────────────────────────────────────────

def test_single_btc_adjusted_equals_raw():
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)  # risk=10
    result = calculate_correlation_risk([btc])
    assert result.adjusted_risk_usdt == result.raw_risk_usdt
    assert result.adjustment_factor == 1.0


def test_single_btc_no_pairs():
    btc = make_btc_long()
    result = calculate_correlation_risk([btc])
    assert result.pairs == []


def test_single_eth_adjusted_equals_raw():
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)  # risk=10
    result = calculate_correlation_risk([eth])
    assert result.adjusted_risk_usdt == result.raw_risk_usdt


# ── BTC + ETH 동일 방향 (LONG + LONG) ────────────────────────────────────────

def test_same_direction_adjusted_less_than_raw():
    """동일 방향: adjusted < raw (ρ=0.85 < 1.0이므로 완전 상관보다 분산 효과)."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)   # risk=10
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth])
    assert float(result.adjusted_risk_usdt) < float(result.raw_risk_usdt)


def test_same_direction_adjusted_formula():
    """adjusted = sqrt(r1² + r2² + 2ρr1r2) with ρ=0.85."""
    r1, r2 = 10.0, 10.0
    rho = BTC_ETH_CORRELATION
    expected = math.sqrt(r1**2 + r2**2 + 2 * rho * r1 * r2)

    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)   # risk=10
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth])
    assert float(result.adjusted_risk_usdt) == pytest.approx(expected, rel=1e-3)


def test_same_direction_positive_effective_rho():
    btc = make_btc_long()
    eth = make_eth_long()
    result = calculate_correlation_risk([btc, eth])
    assert len(result.pairs) == 1
    _, _, _, _, rho = result.pairs[0]
    assert rho > 0


def test_same_direction_short_short():
    btc = make_btc_short(entry=67000.0, sl=68000.0, qty=0.01)   # risk=10
    eth = make_eth_short(entry=3500.0, sl=3600.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth])
    _, _, _, _, rho = result.pairs[0]
    assert rho > 0


# ── BTC + ETH 반대 방향 (헤지) ────────────────────────────────────────────────

def test_opposite_direction_hedge_reduces_risk():
    """반대 방향: ρ=-0.85 → adjusted << raw."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)    # risk=10
    eth = make_eth_short(entry=3500.0, sl=3600.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth])
    # 동일 방향보다 훨씬 낮아야 함
    r1, r2, rho = 10.0, 10.0, -BTC_ETH_CORRELATION
    expected = math.sqrt(r1**2 + r2**2 + 2 * rho * r1 * r2)
    assert float(result.adjusted_risk_usdt) == pytest.approx(expected, rel=1e-3)


def test_opposite_direction_lower_than_same_direction():
    """헤지 포지션의 리스크 < 동일 방향 포지션의 리스크."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth_same = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)
    eth_hedge = make_eth_short(entry=3500.0, sl=3600.0, qty=0.1)

    same_dir = calculate_correlation_risk([btc, eth_same])
    hedge = calculate_correlation_risk([btc, eth_hedge])
    assert float(hedge.adjusted_risk_usdt) < float(same_dir.adjusted_risk_usdt)


def test_opposite_direction_negative_effective_rho():
    btc = make_btc_long()
    eth = make_eth_short()
    result = calculate_correlation_risk([btc, eth])
    _, _, _, _, rho = result.pairs[0]
    assert rho < 0


# ── adjustment_factor ────────────────────────────────────────────────────────

def test_factor_at_most_one():
    """ρ ≤ 1 → adjusted ≤ raw → factor ≤ 1.0."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)
    result = calculate_correlation_risk([btc, eth])
    assert result.adjustment_factor <= 1.0


def test_factor_greater_than_zero():
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)
    result = calculate_correlation_risk([btc, eth])
    assert result.adjustment_factor > 0.0


def test_custom_correlation_zero():
    """ρ=0 → adjusted = sqrt(r1² + r2²) < r1+r2."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)   # risk=10
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth], btc_eth_corr=0.0)
    expected = math.sqrt(10**2 + 10**2)  # ≈ 14.14
    assert float(result.adjusted_risk_usdt) == pytest.approx(expected, rel=1e-3)


# ── 내부 유틸 ────────────────────────────────────────────────────────────────

def test_calc_2asset_risk_perfect_correlation():
    """ρ=1 → adjusted = r1 + r2."""
    result = _calc_2asset_risk(10.0, 10.0, 1.0)
    assert result == pytest.approx(20.0)


def test_calc_2asset_risk_zero_correlation():
    """ρ=0 → adjusted = sqrt(r1² + r2²)."""
    result = _calc_2asset_risk(3.0, 4.0, 0.0)
    assert result == pytest.approx(5.0)


def test_calc_2asset_risk_negative_full():
    """ρ=-1, equal risks → adjusted = 0 (완전 헤지)."""
    result = _calc_2asset_risk(10.0, 10.0, -1.0)
    assert result == pytest.approx(0.0, abs=1e-10)


def test_raw_risk_equals_naive_sum():
    """raw_risk_usdt는 개별 risk 합산 (§3.2 naive sum 방식)."""
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)   # risk=10
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)       # risk=10
    result = calculate_correlation_risk([btc, eth])
    assert result.raw_risk_usdt == Decimal("20.0")
