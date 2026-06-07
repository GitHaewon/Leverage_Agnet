"""
Portfolio Calculator 테스트.

검증:
  - build_snapshot: 빈 포트폴리오, 단일, 복수 포지션
  - notional_value / risk_usdt 계산
  - coin_concentrations 비중 계산
  - check_concentration: §2.4 50% 한도
  - check_single_position_margin: §3.3 20% 한도
  - §10.4 is_emergency 플래그
  - portfolio_weight 합산 = 1.0
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.portfolio.calculator import (
    build_snapshot,
    check_concentration,
    check_single_position_margin,
)

from tests.unit.agents._portfolio_fixtures import (
    make_account,
    make_btc_long,
    make_eth_long,
    make_position,
)


# ── PortfolioPosition 속성 ─────────────────────────────────────────────────────

def test_notional_value_equals_qty_times_current():
    pos = make_btc_long(qty=0.01, current=67000.0)
    # 0.01 × 67000 = 670
    assert pos.notional_value == Decimal("0.01") * Decimal("67000.0")


def test_long_risk_usdt():
    # LONG: risk = (entry - sl) × qty = (67000 - 66000) × 0.01 = 10
    pos = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    assert pos.risk_usdt == Decimal("10.0")


def test_short_risk_usdt():
    # SHORT: risk = (sl - entry) × qty = (68000 - 67000) × 0.01 = 10
    pos = make_position(
        coin="BTC", direction="SHORT",
        entry=67000.0, sl=68000.0, qty=0.01,
    )
    assert pos.risk_usdt == Decimal("10.0")


def test_risk_usdt_clamped_to_zero_for_invalid_sl():
    # sl > entry for LONG → 음수 리스크는 0으로 클램프
    pos = make_btc_long(entry=67000.0, sl=68000.0, qty=0.01)
    assert pos.risk_usdt == Decimal("0")


# ── 빈 포트폴리오 ────────────────────────────────────────────────────────────

def test_empty_snapshot_has_zero_notional():
    acc = make_account(balance=10000.0)
    snap = build_snapshot([], acc)
    assert snap.total_notional == Decimal("0")


def test_empty_snapshot_has_zero_risk():
    acc = make_account()
    snap = build_snapshot([], acc)
    assert snap.total_risk_usdt == Decimal("0")


def test_empty_snapshot_position_count_zero():
    acc = make_account()
    snap = build_snapshot([], acc)
    assert snap.position_count == 0


def test_empty_snapshot_no_emergency():
    acc = make_account(balance=10000.0, initial=10000.0)
    snap = build_snapshot([], acc)
    assert snap.is_emergency is False


# ── 단일 포지션 ──────────────────────────────────────────────────────────────

def test_single_position_notional():
    pos = make_btc_long(qty=0.01, current=67000.0)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.total_notional == Decimal("670.0")


def test_single_position_risk():
    # risk = (67000 - 66000) × 0.01 = 10
    pos = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.total_risk_usdt == Decimal("10.0")


def test_single_position_coin_concentration_100pct():
    pos = make_btc_long()
    acc = make_account()
    snap = build_snapshot([pos], acc)
    assert "BTC" in snap.coin_concentrations
    assert snap.coin_concentrations["BTC"] == pytest.approx(1.0)


def test_single_position_weight_is_one():
    pos = make_btc_long()
    acc = make_account()
    snap = build_snapshot([pos], acc)
    assert snap.symbol_exposures[0].portfolio_weight == pytest.approx(1.0)


def test_single_position_count():
    pos = make_btc_long()
    acc = make_account()
    snap = build_snapshot([pos], acc)
    assert snap.position_count == 1


# ── 복수 포지션 ──────────────────────────────────────────────────────────────

def test_two_positions_total_notional():
    btc = make_btc_long(qty=0.01, current=67000.0)   # notional = 670
    eth = make_eth_long(qty=0.1, current=3500.0)      # notional = 350
    acc = make_account(balance=10000.0)
    snap = build_snapshot([btc, eth], acc)
    assert snap.total_notional == Decimal("1020.0")


def test_two_positions_total_risk():
    # BTC risk = (67000-66000)×0.01 = 10
    # ETH risk = (3500-3400)×0.1 = 10
    btc = make_btc_long(entry=67000.0, sl=66000.0, qty=0.01)
    eth = make_eth_long(entry=3500.0, sl=3400.0, qty=0.1)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([btc, eth], acc)
    assert snap.total_risk_usdt == Decimal("20.0")


def test_two_positions_coin_concentration():
    # BTC: 670 / 1020 ≈ 0.657, ETH: 350 / 1020 ≈ 0.343
    btc = make_btc_long(qty=0.01, current=67000.0)
    eth = make_eth_long(qty=0.1, current=3500.0)
    acc = make_account()
    snap = build_snapshot([btc, eth], acc)
    assert snap.coin_concentrations["BTC"] == pytest.approx(670 / 1020, rel=1e-4)
    assert snap.coin_concentrations["ETH"] == pytest.approx(350 / 1020, rel=1e-4)


def test_portfolio_weights_sum_to_one():
    btc = make_btc_long(qty=0.01, current=67000.0)
    eth = make_eth_long(qty=0.1, current=3500.0)
    acc = make_account()
    snap = build_snapshot([btc, eth], acc)
    total_weight = sum(e.portfolio_weight for e in snap.symbol_exposures)
    assert total_weight == pytest.approx(1.0, abs=1e-5)


def test_total_balance_includes_unrealized_pnl():
    # available=10000, upnl=200 → total=10200
    pos = make_btc_long(upnl=200.0)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.total_balance == Decimal("10200.0")


def test_total_balance_negative_pnl():
    pos = make_btc_long(upnl=-150.0)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.total_balance == Decimal("9850.0")


def test_margin_utilization():
    # margin=200, balance=10000 → 2%
    pos = make_btc_long(margin=200.0)
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.margin_utilization == pytest.approx(0.02)


# ── check_concentration (§2.4) ───────────────────────────────────────────────

def test_concentration_pass_single_coin():
    """단일 코인 포지션 = 100% 집중도 → 통과 (포지션이 1개면 다른 코인 없음)."""
    pos = make_btc_long()
    acc = make_account()
    snap = build_snapshot([pos], acc)
    # 단일 코인 = 100% → 한도(50%) 초과이므로 실제로는 fail
    ok, _ = check_concentration(snap)
    assert not ok  # 100% > 50%


def test_concentration_pass_equal_two_coins():
    """BTC 50% + ETH 50% = 한도 경계 → 통과 (> 아니고 == 이므로)."""
    btc = make_btc_long(qty=0.01, current=67000.0)  # 670
    # ETH notional = 670이 되도록: qty = 670/3500 ≈ 0.1914
    eth = make_position(
        coin="ETH", symbol="ETHUSDT", direction="LONG",
        qty=670 / 3500, current=3500.0, entry=3500.0, sl=3400.0,
    )
    acc = make_account()
    snap = build_snapshot([btc, eth], acc)
    ok, reason = check_concentration(snap)
    # 정확히 50%이면 > 50% 조건 불충족 → 통과
    assert ok


def test_concentration_fail_btc_dominant():
    """BTC가 명목 가치의 70% → §2.4 위반."""
    btc = make_btc_long(qty=0.1, current=67000.0)   # 6700
    eth = make_eth_long(qty=0.1, current=3500.0)     # 350 (6700/(6700+350)≈0.95)
    acc = make_account()
    snap = build_snapshot([btc, eth], acc)
    ok, reason = check_concentration(snap)
    assert not ok
    assert "CONCENTRATION" in reason
    assert "BTC" in reason


# ── check_single_position_margin (§3.3) ──────────────────────────────────────

def test_margin_check_pass():
    # margin=200, balance=10000 → 2% < 20%
    pos = make_btc_long(margin=200.0)
    acc = make_account(balance=10000.0)
    ok, _ = check_single_position_margin(pos, acc)
    assert ok


def test_margin_check_fail():
    # margin=2500, balance=10000 → 25% > 20%
    pos = make_btc_long(margin=2500.0)
    acc = make_account(balance=10000.0)
    ok, reason = check_single_position_margin(pos, acc)
    assert not ok
    assert "MARGIN_LIMIT" in reason


def test_margin_check_exact_limit_passes():
    # margin=2000, balance=10000 → 20% = 한도 → 통과 (> 아님)
    pos = make_btc_long(margin=2000.0)
    acc = make_account(balance=10000.0)
    ok, _ = check_single_position_margin(pos, acc)
    assert ok


# ── §10.4 비상 상태 ───────────────────────────────────────────────────────────

def test_emergency_when_balance_below_10pct_of_initial():
    # balance=900, initial=10000 → 9% < 10% → 비상
    acc = make_account(balance=900.0, initial=10000.0)
    snap = build_snapshot([], acc)
    assert snap.is_emergency is True


def test_no_emergency_normal_balance():
    acc = make_account(balance=9000.0, initial=10000.0)
    snap = build_snapshot([], acc)
    assert snap.is_emergency is False


def test_no_emergency_at_exact_threshold():
    # balance=1000, initial=10000 → 10% = 임계값 → 비상 아님 (< 조건)
    acc = make_account(balance=1000.0, initial=10000.0)
    snap = build_snapshot([], acc)
    assert snap.is_emergency is False


def test_total_risk_pct_calculation():
    # risk=500, balance=10000 → 5%
    pos = make_btc_long(entry=67000.0, sl=17000.0, qty=0.01)  # risk = 50000×0.01 = 500
    acc = make_account(balance=10000.0)
    snap = build_snapshot([pos], acc)
    assert snap.total_risk_pct == pytest.approx(0.05)
