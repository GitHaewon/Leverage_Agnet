"""
PortfolioEngine 통합 테스트.

검증:
  - engine.snapshot()
  - engine.correlation_risk()
  - engine.risk_score()
  - engine.can_add_position() — 허용 / §3.2 초과 / §10.4 비상
  - engine.check_concentration()
  - engine.check_margin()
  - 커스텀 상관계수 적용
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.portfolio.engine import PortfolioEngine

from tests.unit.agents._portfolio_fixtures import (
    make_account,
    make_btc_long,
    make_btc_short,
    make_eth_long,
    make_eth_short,
    make_position,
)


ENGINE = PortfolioEngine()


# ── snapshot ──────────────────────────────────────────────────────────────────

def test_engine_snapshot_empty():
    acc = make_account(balance=10000.0)
    snap = ENGINE.snapshot([], acc)
    assert snap.position_count == 0
    assert snap.total_notional == Decimal("0")


def test_engine_snapshot_single_position():
    pos = make_btc_long(qty=0.01, current=67000.0)
    acc = make_account(balance=10000.0)
    snap = ENGINE.snapshot([pos], acc)
    assert snap.position_count == 1
    assert snap.total_notional == Decimal("670.0")


def test_engine_snapshot_has_symbol_exposures():
    pos = make_btc_long()
    acc = make_account()
    snap = ENGINE.snapshot([pos], acc)
    assert len(snap.symbol_exposures) == 1
    assert snap.symbol_exposures[0].coin == "BTC"


def test_engine_snapshot_total_balance():
    pos = make_btc_long(upnl=100.0)
    acc = make_account(balance=10000.0)
    snap = ENGINE.snapshot([pos], acc)
    assert snap.total_balance == Decimal("10100.0")


# ── correlation_risk ──────────────────────────────────────────────────────────

def test_engine_correlation_single_asset_no_adjustment():
    pos = make_btc_long()
    result = ENGINE.correlation_risk([pos])
    assert result.adjustment_factor == 1.0
    assert result.pairs == []


def test_engine_correlation_btc_eth_same_direction():
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)
    result = ENGINE.correlation_risk([btc, eth])
    assert len(result.pairs) == 1
    assert result.adjustment_factor < 1.0


def test_engine_correlation_btc_eth_hedge():
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth = make_eth_short(entry=3500.0, sl=3600.0, qty=0.1)
    result = ENGINE.correlation_risk([btc, eth])
    # 헤지 → adjusted < 동일 방향 케이스
    _, _, _, _, rho = result.pairs[0]
    assert rho < 0


def test_engine_custom_correlation():
    """ρ=0 커스텀 엔진 → factor = sqrt(r1²+r2²)/(r1+r2) < 1."""
    engine_no_corr = PortfolioEngine(btc_eth_correlation=0.0)
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)   # risk=10
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)       # risk=10
    result = engine_no_corr.correlation_risk([btc, eth])
    # sqrt(200) / 20 ≈ 0.707
    import math
    assert result.adjustment_factor == pytest.approx(math.sqrt(200) / 20, rel=1e-3)


# ── risk_score ────────────────────────────────────────────────────────────────

def test_engine_risk_score_empty_safe():
    acc = make_account(balance=10000.0, initial=10000.0)
    score = ENGINE.risk_score([], acc)
    assert score.level == "safe"
    assert score.score == pytest.approx(0.0)


def test_engine_risk_score_has_components():
    pos = make_btc_long(leverage=10)
    acc = make_account(balance=10000.0, initial=10000.0)
    score = ENGINE.risk_score([pos], acc)
    assert score.components.leverage_ratio > 0


def test_engine_risk_score_level_not_none():
    pos = make_btc_long()
    acc = make_account()
    score = ENGINE.risk_score([pos], acc)
    assert score.level in ("safe", "moderate", "elevated", "critical")


# ── can_add_position ──────────────────────────────────────────────────────────

def test_engine_can_add_when_under_limit():
    acc = make_account(balance=10000.0, initial=10000.0)
    ok, reason = ENGINE.can_add_position([], acc, Decimal("500"))
    assert ok
    assert reason == "OK"


def test_engine_cannot_add_when_exceeds_limit():
    """기존 risk=900 + 신규 200 = 1100 > limit=1000 → 거부."""
    # risk=(67000-58000)×0.1 = 900
    pos = make_btc_long(entry=67000.0, sl=58000.0, qty=0.1)
    acc = make_account(balance=10000.0, initial=10000.0)
    ok, reason = ENGINE.can_add_position([pos], acc, Decimal("200"))
    assert not ok
    assert "PORTFOLIO_RISK" in reason


def test_engine_cannot_add_when_emergency():
    acc = make_account(balance=500.0, initial=10000.0)
    ok, reason = ENGINE.can_add_position([], acc, Decimal("10"))
    assert not ok
    assert "EMERGENCY" in reason


def test_engine_can_add_at_exact_limit():
    """신규 리스크 = 남은 한도 정확히 → 허용 (projected == limit, > 아님)."""
    # limit=1000, existing=0 → add=1000 → projected=1000, not > 1000
    acc = make_account(balance=10000.0, initial=10000.0)
    ok, _ = ENGINE.can_add_position([], acc, Decimal("1000"))
    assert ok


def test_engine_cannot_add_one_over_limit():
    """projected = limit + 1 → 거부."""
    acc = make_account(balance=10000.0, initial=10000.0)
    ok, _ = ENGINE.can_add_position([], acc, Decimal("1000.01"))
    assert not ok


# ── check_concentration ───────────────────────────────────────────────────────

def test_engine_concentration_pass_equal_weights():
    btc = make_btc_long(qty=0.01, current=67000.0)
    eth = make_position(
        coin="ETH", direction="LONG",
        qty=670 / 3500, current=3500.0, entry=3500.0, sl=3400.0,
    )
    acc = make_account()
    ok, _ = ENGINE.check_concentration([btc, eth], acc)
    assert ok


def test_engine_concentration_fail_dominant_coin():
    btc = make_btc_long(qty=0.1, current=67000.0)   # 6700
    eth = make_eth_long(qty=0.1, current=3500.0)     # 350
    acc = make_account()
    ok, reason = ENGINE.check_concentration([btc, eth], acc)
    assert not ok
    assert "CONCENTRATION" in reason


# ── check_margin ──────────────────────────────────────────────────────────────

def test_engine_margin_pass():
    pos = make_btc_long(margin=200.0)
    acc = make_account(balance=10000.0)
    ok, _ = ENGINE.check_margin(pos, acc)
    assert ok


def test_engine_margin_fail():
    pos = make_btc_long(margin=3000.0)
    acc = make_account(balance=10000.0)
    ok, reason = ENGINE.check_margin(pos, acc)
    assert not ok
    assert "MARGIN_LIMIT" in reason
