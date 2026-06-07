"""
Position Manager — DCA 테스트.

검증:
  - check_dca_eligibility: 5개 조건 각각 거부
  - check_dca_eligibility: 모든 조건 충족 시 OK
  - apply_dca: 가중평균 진입가 재계산 (§8.3)
  - apply_dca: dca_count 증가
  - apply_dca: 청산가 재계산
  - apply_dca: 수량 / 증거금 합산
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.position_manager.dca import apply_dca, check_dca_eligibility, _recalculate_avg_entry
from agents.position_manager.models import MAX_DCA_COUNT

from tests.unit.agents._pm_fixtures import make_account, make_position, make_validation


ENTRY = 67000.0
ATR = Decimal("300.0")


def _make_pos(**kwargs):
    defaults = dict(
        direction="LONG", entry=ENTRY, tp=70000.0, sl=66000.0,
        qty=0.01, leverage=5, margin=134.0, original_risk=10.0,
    )
    defaults.update(kwargs)
    return make_position(**defaults)


def _make_acc(**kwargs):
    defaults = dict(daily_limit=100.0, weekly_limit=300.0)
    defaults.update(kwargs)
    return make_account(**defaults)


# ── check_dca_eligibility 거부 조건 ──────────────────────────────────────────

def test_dca_rejected_wrong_direction():
    pos = _make_pos(direction="LONG")
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "SHORT",
        dca_entry_price=Decimal("66700"),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_DIRECTION" in result.reason


def test_dca_rejected_max_count_exceeded():
    pos = _make_pos(dca_count=MAX_DCA_COUNT)
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal("66700"),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_LIMIT" in result.reason


def test_dca_rejected_insufficient_price_move():
    pos = _make_pos(entry=ENTRY)
    # 가격 이동이 ATR(300)의 1.0배 = 300 미만 → 200 이동
    dca_price = Decimal(str(ENTRY - 200))
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=dca_price,
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_PREMATURE" in result.reason


def test_dca_rejected_risk_limit_exceeded():
    # original_risk=10, DCA_RISK_MULTIPLIER=2.0 → 총 리스크 20 초과 불가
    # 현재 포지션 리스크 ≈ (67000 - 66000) × 0.01 = 10
    # dca_risk=15 → total ≈ 25 > 20
    pos = _make_pos(entry=ENTRY, original_risk=10.0)
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),  # 충분한 가격 이동
        dca_risk_usdt=Decimal("15"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_RISK" in result.reason


def test_dca_rejected_daily_loss_warning():
    # 일일 손실 70/100 = 70% ≥ 50% 경고
    acc = _make_acc(daily_loss=70.0, daily_limit=100.0)
    pos = _make_pos(entry=ENTRY, original_risk=50.0)
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_FORBIDDEN" in result.reason


def test_dca_rejected_cooldown():
    acc = _make_acc(in_cooldown=True)
    pos = _make_pos(entry=ENTRY, original_risk=50.0)
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "쿨다운" in result.reason


def test_dca_rejected_weekly_loss_warning():
    # 주간 손실 240/300 = 80% ≥ 75% 경고
    acc = _make_acc(weekly_loss=240.0, weekly_limit=300.0)
    pos = _make_pos(entry=ENTRY, original_risk=50.0)
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_FORBIDDEN" in result.reason


def test_dca_rejected_drawdown_over_5pct():
    # 진입 67000, 현재가 63000 → drawdown = (67000-63000)×0.01 / 134 ≈ 29.8%
    pos = _make_pos(entry=ENTRY, current_price=63000.0, original_risk=50.0)
    pos.current_price = Decimal("63000.0")  # 명시적 설정
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert not result.eligible
    assert "DCA_FORBIDDEN" in result.reason


def test_dca_eligible_all_conditions_met():
    pos = _make_pos(entry=ENTRY, original_risk=50.0)
    acc = _make_acc()
    result = check_dca_eligibility(
        pos, "LONG",
        dca_entry_price=Decimal(str(ENTRY - 400)),  # 400 이동 ≥ ATR 300
        dca_risk_usdt=Decimal("5"),
        current_atr=ATR,
        account=acc,
    )
    assert result.eligible
    assert result.reason == "OK"


# ── apply_dca ────────────────────────────────────────────────────────────────

def test_apply_dca_recalculates_avg_entry():
    """§8.3: 가중평균 진입가 = (qty1×entry1 + qty2×entry2) / (qty1+qty2)."""
    pos = _make_pos(entry=67000.0, qty=0.01)
    dca_entry = Decimal("66400.0")
    val = make_validation(qty=0.01, leverage=5, margin=134.0, max_loss=6.0)

    result = apply_dca(pos, dca_entry, val)

    # (0.01×67000 + 0.01×66400) / 0.02 = 66700
    expected_avg = (Decimal("0.01") * Decimal("67000") + Decimal("0.01") * Decimal("66400.0")) / Decimal("0.02")
    assert result.new_avg_entry == expected_avg.quantize(Decimal("0.01"))
    assert result.position.entry_price == expected_avg.quantize(Decimal("0.01"))


def test_apply_dca_increments_count():
    pos = _make_pos(entry=ENTRY, qty=0.01, dca_count=0)
    val = make_validation(qty=0.01)
    apply_dca(pos, Decimal("66400"), val)
    assert pos.dca_count == 1


def test_apply_dca_adds_quantity():
    pos = _make_pos(entry=ENTRY, qty=0.01)
    val = make_validation(qty=0.01)
    result = apply_dca(pos, Decimal("66400"), val)
    assert pos.quantity == Decimal("0.02")
    assert result.added_quantity == Decimal("0.01")


def test_apply_dca_adds_margin():
    pos = _make_pos(entry=ENTRY, margin=134.0)
    val = make_validation(qty=0.01, margin=134.0)
    result = apply_dca(pos, Decimal("66400"), val)
    assert pos.margin_used == Decimal("268.0")
    assert result.added_margin == Decimal("134.0")


def test_apply_dca_recalculates_liquidation_price():
    pos = _make_pos(entry=ENTRY, qty=0.01, leverage=5)
    original_liq = pos.liquidation_price
    val = make_validation(qty=0.01, leverage=5)
    apply_dca(pos, Decimal("66400"), val)
    # 새 avg_entry(66700)로 청산가 재계산 → 원래보다 낮아야
    assert pos.liquidation_price != original_liq


# ── _recalculate_avg_entry 직접 테스트 ──────────────────────────────────────

def test_recalculate_avg_entry_equal_sizes():
    avg = _recalculate_avg_entry(
        Decimal("0.01"), Decimal("67000"),
        Decimal("0.01"), Decimal("66000"),
    )
    assert avg == Decimal("66500.00")


def test_recalculate_avg_entry_unequal_sizes():
    # 0.02@67000 + 0.01@65000 → (134 + 65) / 0.03 = 66333.33...
    avg = _recalculate_avg_entry(
        Decimal("0.02"), Decimal("67000"),
        Decimal("0.01"), Decimal("65000"),
    )
    expected = ((Decimal("0.02") * Decimal("67000")) + (Decimal("0.01") * Decimal("65000"))) / Decimal("0.03")
    assert avg == expected.quantize(Decimal("0.01"))
