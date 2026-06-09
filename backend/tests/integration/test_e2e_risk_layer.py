"""
E2E-02: Signal → Risk 검증 레이어 (15 tests).

DB / API Key 없이 TRADING_RULES.md 규칙을 직접 검증한다.
Risk Agent 코드와 1:1 대응.

검증 항목:
  §7.4  R:R 최소 2.0
  §11.3 신뢰도 최소 60%
  §1.1  레버리지 상한 20x
  §4    HOLD 시그널 거부
  §7.1  포지션 사이징 공식
  §3.1  Risk Per Trade 범위 0.5% ~ 5%
"""
from __future__ import annotations

import pytest

from .conftest_testnet import (
    MIN_CONFIDENCE,
    MIN_RR_RATIO,
    RISK_PER_TRADE_MAX,
    RISK_PER_TRADE_MIN,
    SYSTEM_MAX_LEVE,
    compute_position_size,
    validate_signal_rules,
)


class TestSignalRiskValidation:
    """TRADING_RULES.md 시그널 검증 규칙 (§7.4, §11.3, §1.1)."""

    # ── 유효 시그널 ─────────────────────────────────────────────────────────────

    def test_valid_long_signal_passes(self) -> None:
        """정상 LONG 시그널 — 모든 조건 통과."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,    # R:R = 2000/1000 = 2.0
            confidence=0.80,
            leverage=5,
        )
        assert ok is True, reason

    def test_valid_short_signal_passes(self) -> None:
        """정상 SHORT 시그널 — 모든 조건 통과."""
        ok, reason = validate_signal_rules(
            direction="SHORT",
            stop_loss=68_000.0,
            entry=67_000.0,
            take_profit=65_000.0,    # R:R = 2000/1000 = 2.0
            confidence=0.75,
            leverage=3,
        )
        assert ok is True, reason

    def test_exact_minimum_rr_passes(self) -> None:
        """R:R = 2.0 정확히 최솟값 — 통과해야 한다."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=65_000.0,
            entry=67_000.0,
            take_profit=71_000.0,    # R:R = 4000/2000 = 2.0
            confidence=0.60,
            leverage=1,
        )
        assert ok is True, reason

    def test_exact_minimum_confidence_passes(self) -> None:
        """신뢰도 60.0% — 최솟값에서 통과."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=MIN_CONFIDENCE,
            leverage=5,
        )
        assert ok is True, reason

    # ── HOLD 시그널 거부 ─────────────────────────────────────────────────────────

    def test_hold_signal_is_rejected(self) -> None:
        """HOLD 시그널은 반드시 거부 (§C0 체크)."""
        ok, reason = validate_signal_rules(
            direction="HOLD",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.90,
            leverage=5,
        )
        assert ok is False
        assert "HOLD" in reason

    # ── Stop Loss 없는 주문 금지 ─────────────────────────────────────────────────

    def test_missing_stop_loss_is_rejected(self) -> None:
        """SL 없는 주문 — 절대 규칙 #4 위반."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=None,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.80,
            leverage=5,
        )
        assert ok is False
        assert "ORDER_003" in reason

    def test_zero_stop_loss_is_rejected(self) -> None:
        """SL = 0 — 사실상 SL 없음과 동일."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=0.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.80,
            leverage=5,
        )
        assert ok is False

    def test_long_sl_above_entry_rejected(self) -> None:
        """LONG인데 SL > entry — 방향 오류."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=68_000.0,   # entry보다 높음 — 말이 안 됨
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.80,
            leverage=5,
        )
        assert ok is False

    # ── R:R 최소 2.0 미달 거부 ──────────────────────────────────────────────────

    def test_rr_below_minimum_rejected(self) -> None:
        """R:R = 1.5 (< 2.0) — ORDER_004 거부."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=68_500.0,   # R:R = 1500/1000 = 1.5
            confidence=0.80,
            leverage=5,
        )
        assert ok is False
        assert "ORDER_004" in reason

    def test_rr_exactly_below_minimum_rejected(self) -> None:
        """R:R = 1.99 (< 2.0) — 경계값 거부."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=68_990.0,   # R:R = 1990/1000 = 1.99
            confidence=0.80,
            leverage=5,
        )
        assert ok is False

    # ── 신뢰도 60% 미달 거부 ──────────────────────────────────────────────────────

    def test_low_confidence_rejected(self) -> None:
        """신뢰도 59% — LOW_CONFIDENCE 거부."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.59,
            leverage=5,
        )
        assert ok is False
        assert "LOW_CONFIDENCE" in reason

    def test_zero_confidence_rejected(self) -> None:
        """신뢰도 0% — 즉시 거부."""
        ok, reason = validate_signal_rules(
            direction="SHORT",
            stop_loss=68_000.0,
            entry=67_000.0,
            take_profit=65_000.0,
            confidence=0.0,
            leverage=3,
        )
        assert ok is False

    # ── 레버리지 상한 20x ────────────────────────────────────────────────────────

    def test_leverage_over_system_max_rejected(self) -> None:
        """레버리지 21x > SYSTEM_MAX_LEVERAGE(20x) — 거부."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.80,
            leverage=21,
        )
        assert ok is False
        assert "LEVERAGE" in reason

    def test_max_leverage_exactly_passes(self) -> None:
        """레버리지 20x (= SYSTEM_MAX_LEVERAGE) — 통과."""
        ok, reason = validate_signal_rules(
            direction="LONG",
            stop_loss=66_000.0,
            entry=67_000.0,
            take_profit=69_000.0,
            confidence=0.80,
            leverage=SYSTEM_MAX_LEVE,
        )
        assert ok is True, reason


class TestPositionSizing:
    """TRADING_RULES.md §7.1 포지션 사이징 공식 검증."""

    def test_sizing_formula_correctness(self) -> None:
        """
        §7.1 공식 검증:
          quantity = risk_amount / sl_distance
          margin   = (quantity × entry) / leverage
        """
        balance        = 10_000.0
        risk_per_trade = 0.02           # 2%
        entry          = 67_000.0
        stop_loss      = 66_000.0       # SL 거리 = $1,000
        leverage       = 5

        qty, margin = compute_position_size(balance, risk_per_trade, entry, stop_loss, leverage)

        # risk_amount = $200, sl_distance = $1,000 → qty = 0.2 BTC
        expected_qty    = 10_000 * 0.02 / 1_000  # 0.2
        expected_margin = (expected_qty * entry) / leverage  # $2,680

        assert abs(float(qty) - expected_qty)    < 0.001, f"quantity 불일치: {qty} vs {expected_qty}"
        assert abs(float(margin) - expected_margin) < 1.0, f"margin 불일치: {margin} vs {expected_margin}"

    def test_sizing_scales_with_balance(self) -> None:
        """잔고가 2배 → 수량이 2배."""
        qty_1k, _ = compute_position_size(10_000.0, 0.02, 67_000.0, 66_000.0, 5)
        qty_2k, _ = compute_position_size(20_000.0, 0.02, 67_000.0, 66_000.0, 5)
        assert abs(float(qty_2k) / float(qty_1k) - 2.0) < 0.01

    def test_sizing_zero_sl_distance_raises(self) -> None:
        """SL = entry → sl_distance = 0 → ValueError."""
        with pytest.raises(ValueError, match="sl_distance is zero"):
            compute_position_size(10_000.0, 0.02, 67_000.0, 67_000.0, 5)

    def test_risk_per_trade_min_bound(self) -> None:
        """risk_per_trade = 0.5% (최솟값) — 정상 동작."""
        qty, margin = compute_position_size(10_000.0, RISK_PER_TRADE_MIN, 67_000.0, 66_000.0, 5)
        assert qty > 0
        assert margin > 0

    def test_risk_per_trade_max_bound(self) -> None:
        """risk_per_trade = 5% (최댓값) — 정상 동작."""
        qty, margin = compute_position_size(10_000.0, RISK_PER_TRADE_MAX, 67_000.0, 66_000.0, 5)
        assert qty > 0
        # 5% 리스크는 0.5% 리스크의 10배 수량이어야 함
        qty_min, _ = compute_position_size(10_000.0, RISK_PER_TRADE_MIN, 67_000.0, 66_000.0, 5)
        ratio = float(qty) / float(qty_min)
        assert abs(ratio - 10.0) < 0.01
