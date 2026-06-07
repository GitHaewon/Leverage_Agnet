"""
Portfolio Scorer 테스트.

검증:
  - 빈 포트폴리오 → score=0, level="safe"
  - 리스크 한도 도달 → 높은 점수
  - 레벨 매핑 (safe/moderate/elevated/critical)
  - §3.2 breach: 총 리스크 한도 초과
  - §3.2 warning: 총 리스크 80% 도달
  - §2.4 breach: 집중도 50% 초과
  - §10.4 breach: 비상 잔고
  - can_add_position 로직
  - max_additional_risk_usdt 계산
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.portfolio.calculator import build_snapshot
from agents.portfolio.correlation import calculate_correlation_risk
from agents.portfolio.scorer import calculate_risk_score

from tests.unit.agents._portfolio_fixtures import (
    make_account,
    make_btc_long,
    make_eth_long,
    make_position,
)


def _score(positions, account):
    snap = build_snapshot(positions, account)
    corr = calculate_correlation_risk(positions)
    leverages = [p.leverage for p in positions]
    return calculate_risk_score(snap, corr, account, leverages)


# ── 빈 포트폴리오 ─────────────────────────────────────────────────────────────

def test_empty_portfolio_score_zero():
    acc = make_account(balance=10000.0, initial=10000.0)
    result = _score([], acc)
    assert result.score == pytest.approx(0.0)


def test_empty_portfolio_level_safe():
    acc = make_account()
    result = _score([], acc)
    assert result.level == "safe"


def test_empty_portfolio_no_breaches():
    acc = make_account()
    result = _score([], acc)
    assert result.breaches == []


def test_empty_portfolio_can_add():
    acc = make_account(balance=10000.0)
    result = _score([], acc)
    assert result.can_add_position is True


def test_empty_portfolio_max_additional_risk_equals_limit():
    # balance=10000, moderate → limit=10% → max=1000
    acc = make_account(balance=10000.0, profile="moderate")
    result = _score([], acc)
    assert result.max_additional_risk_usdt == Decimal("1000.0")


# ── 레벨 매핑 ────────────────────────────────────────────────────────────────

def test_level_safe_below_30():
    """score < 0.30 → safe."""
    acc = make_account(balance=10000.0)
    # risk 0, leverage 5 → score = 0 + 0 + 0 + (5/20)×0.15 = 0.0375
    pos = make_btc_long(entry=67000.0, sl=66999.0, qty=0.001, leverage=5)  # 극소 risk
    result = _score([pos], acc)
    assert result.level == "safe"


def test_level_critical_at_high_score():
    """BTC+ETH 동일 방향 + 높은 리스크 + 상관 페널티 → critical (score ≥ 0.75)."""
    # balance=1000, moderate → limit=100
    # BTC risk=100, ETH risk=100 → portfolio_risk_ratio=1.0 (clamped)
    # concentration: BTC≈65% > 50% → ratio=1.0 (clamped)
    # correlation penalty: same dir → 0.85
    # leverage: (5+5)/2 / 20 = 0.25
    # score = 0.40+0.25+(0.85×0.20)+(0.25×0.15) = 0.40+0.25+0.17+0.0375 = 0.8575
    acc = make_account(balance=1000.0, initial=1000.0)
    btc = make_btc_long(entry=67000.0, sl=57000.0, qty=0.01, leverage=5)   # risk=100
    eth = make_eth_long(entry=3500.0, sl=2500.0, qty=0.1, leverage=5)       # risk=100
    result = _score([btc, eth], acc)
    assert result.level == "critical"


# ── §3.2 총 리스크 breach / warning ──────────────────────────────────────────

def test_breach_when_total_risk_exceeds_limit():
    """total_risk > limit → PORTFOLIO_RISK breach."""
    # balance=1000, moderate → limit=100
    # risk=(67000-66000)×0.1 = 100 USDT → risk == limit → breach (≥ 1.0)
    acc = make_account(balance=1000.0, initial=1000.0)
    pos = make_btc_long(entry=67000.0, sl=66000.0, qty=0.1)   # risk=100
    result = _score([pos], acc)
    any_portfolio_breach = any("PORTFOLIO_RISK" in b for b in result.breaches)
    assert any_portfolio_breach


def test_warning_at_80pct_of_limit():
    """total_risk = 80% of limit → warning, no breach."""
    # balance=10000, moderate → limit=1000
    # risk=800 USDT = 80%
    acc = make_account(balance=10000.0, initial=10000.0)
    pos = make_btc_long(entry=67000.0, sl=57000.0, qty=0.08)   # risk=800
    result = _score([pos], acc)
    has_warning = any("PORTFOLIO_RISK_WARNING" in w for w in result.warnings)
    assert has_warning
    has_breach = any("PORTFOLIO_RISK" in b for b in result.breaches)
    assert not has_breach


def test_no_warning_below_80pct():
    """risk < 80% of limit → 경고 없음."""
    acc = make_account(balance=10000.0, initial=10000.0)
    pos = make_btc_long(entry=67000.0, sl=60000.0, qty=0.01)   # risk=70
    result = _score([pos], acc)
    has_warning = any("PORTFOLIO_RISK_WARNING" in w for w in result.warnings)
    assert not has_warning


# ── §2.4 집중도 breach ────────────────────────────────────────────────────────

def test_breach_concentration_over_50pct():
    """BTC 90% 집중 → CONCENTRATION breach."""
    btc = make_btc_long(qty=0.1, current=67000.0)   # notional=6700
    eth = make_eth_long(qty=0.1, current=3500.0)     # notional=350
    acc = make_account(balance=10000.0)
    result = _score([btc, eth], acc)
    assert any("CONCENTRATION" in b for b in result.breaches)


def test_no_concentration_breach_for_equal_weights():
    """BTC 50% ETH 50% = 한도 정확히 경계 → breach 없음."""
    btc = make_btc_long(qty=0.01, current=67000.0)   # notional=670
    eth = make_position(
        coin="ETH", direction="LONG",
        qty=670 / 3500, current=3500.0, entry=3500.0, sl=3400.0,
    )
    acc = make_account()
    result = _score([btc, eth], acc)
    assert not any("CONCENTRATION" in b for b in result.breaches)


# ── §10.4 비상 breach ────────────────────────────────────────────────────────

def test_breach_emergency_balance():
    """잔고 < initial×10% → EMERGENCY breach."""
    acc = make_account(balance=500.0, initial=10000.0)
    result = _score([], acc)
    assert any("EMERGENCY" in b for b in result.breaches)


def test_no_breach_normal_balance():
    acc = make_account(balance=10000.0, initial=10000.0)
    result = _score([], acc)
    assert not any("EMERGENCY" in b for b in result.breaches)


# ── can_add_position ─────────────────────────────────────────────────────────

def test_cannot_add_when_emergency():
    acc = make_account(balance=500.0, initial=10000.0)
    result = _score([], acc)
    assert result.can_add_position is False


def test_cannot_add_when_breach():
    # 총 리스크 한도 초과
    acc = make_account(balance=1000.0, initial=1000.0)
    pos = make_btc_long(entry=67000.0, sl=57000.0, qty=0.01)   # risk=100 == limit
    result = _score([pos], acc)
    assert result.can_add_position is False


def test_can_add_with_remaining_capacity():
    """3개 코인 각 < 50% 집중도, 낮은 risk → 추가 포지션 허용."""
    # BTC notional=335 (42.7%), ETH notional=350 (44.6%), SOL notional=100 (12.7%)
    # 모든 코인 < 50% → 집중도 breach 없음
    # total_risk=25 / limit=1000 → 여유 있음
    acc = make_account(balance=10000.0, initial=10000.0)
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.005)    # notional=335, risk=5
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)         # notional=350, risk=10
    sol = make_position(
        coin="SOL", direction="LONG",
        entry=100.0, sl=90.0, qty=1.0, current=100.0,
    )  # notional=100, risk=10
    result = _score([btc, eth, sol], acc)
    assert result.can_add_position is True


# ── max_additional_risk_usdt ─────────────────────────────────────────────────

def test_max_additional_decreases_with_existing_risk():
    # balance=10000, limit=1000, existing_risk=300 → remaining=700
    acc = make_account(balance=10000.0, initial=10000.0)
    pos = make_btc_long(entry=67000.0, sl=37000.0, qty=0.01)   # risk=300
    result = _score([pos], acc)
    assert result.max_additional_risk_usdt == pytest.approx(Decimal("700.0"), abs=Decimal("1"))


def test_max_additional_zero_when_at_limit():
    # balance=1000, limit=100, risk=100
    acc = make_account(balance=1000.0, initial=1000.0)
    pos = make_btc_long(entry=67000.0, sl=57000.0, qty=0.01)   # risk=100
    result = _score([pos], acc)
    assert result.max_additional_risk_usdt == Decimal("0")


# ── 컴포넌트 값 ──────────────────────────────────────────────────────────────

def test_leverage_ratio_component():
    """leverage=10, system_max=20 → leverage_ratio=0.5."""
    acc = make_account(balance=10000.0, initial=10000.0)
    pos = make_btc_long(leverage=10, entry=67000.0, sl=66900.0, qty=0.001)  # 극소 risk
    snap = build_snapshot([pos], acc)
    corr = calculate_correlation_risk([pos])
    score_obj = calculate_risk_score(snap, corr, acc, [10])
    assert score_obj.components.leverage_ratio == pytest.approx(0.5)


def test_aggressive_profile_higher_limit():
    """공격형(15%) > 중립형(10%) → 동일 리스크에서 공격형 점수 낮음."""
    pos = make_btc_long(entry=67000.0, sl=60000.0, qty=0.01)   # risk=70
    acc_mod = make_account(balance=10000.0, profile="moderate")    # limit=1000
    acc_agg = make_account(balance=10000.0, profile="aggressive")  # limit=1500
    result_mod = _score([pos], acc_mod)
    result_agg = _score([pos], acc_agg)
    assert result_mod.components.portfolio_risk_ratio > result_agg.components.portfolio_risk_ratio
