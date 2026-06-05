"""
PaperRiskEngine 단위 테스트 — TRADING_RULES.md §11.1 12단계 검증 커버리지.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from agents.risk.models import RawSignal
from agents.paper_trading.models import PaperUserSettings
from agents.paper_trading.risk_engine import PaperRiskEngine
from agents.paper_trading.state import PaperAccountState


# ── 공통 픽스처 ────────────────────────────────────────────────────────────────

def _settings(**kwargs) -> PaperUserSettings:
    # risk_per_trade=0.005 (0.5%), leverage=20 사용 이유:
    # quantity = risk_amount / sl_distance = (10000×0.005) / 650 = 0.076 BTC
    # margin   = 0.076 × 67450 / 20 = $256 = 2.56% ≤ 20% 한도 ✓
    defaults = dict(
        user_id="u1",
        plan="elite",
        risk_profile="aggressive",
        risk_per_trade=0.005,
        max_leverage=20,
        max_concurrent_positions=5,
        daily_loss_limit_pct=0.05,
        weekly_loss_limit_pct=0.15,
        is_trading_active=True,
    )
    defaults.update(kwargs)
    return PaperUserSettings(**defaults)


def _account(balance: float = 10000.0, **kwargs) -> PaperAccountState:
    return PaperAccountState(
        user_id="u1",
        _balance=Decimal(str(balance)),
        initial_balance=Decimal(str(balance)),
        **kwargs,
    )


def _signal(**kwargs) -> RawSignal:
    """
    기본 유효한 LONG BTC 시그널.
    leverage=20 사용: margin = (50/650)×67450/20 = $256 = 2.56% ≤ 20% 한도 ✓
    """
    defaults = dict(
        direction="LONG",
        coin="BTC",
        symbol="BTCUSDT",
        confidence=0.85,
        entry_price=Decimal("67450"),
        take_profit=Decimal("69200"),  # R:R = 1750/650 = 2.69 ✓
        stop_loss=Decimal("66800"),
        leverage=20,
    )
    defaults.update(kwargs)
    return RawSignal(**defaults)


@pytest.fixture
def engine() -> PaperRiskEngine:
    return PaperRiskEngine()


@pytest.fixture
def valid_signal() -> RawSignal:
    return _signal()


@pytest.fixture
def account() -> PaperAccountState:
    return _account(10000)


@pytest.fixture
def settings() -> PaperUserSettings:
    return _settings()


# ── CHECK 0: Halt ─────────────────────────────────────────────────────────────

class TestHaltCheck:
    def test_halted_account_rejected(self, engine, valid_signal, settings):
        acc = _account()
        acc.halt("daily_loss")
        result = engine.validate(valid_signal, settings, acc)
        assert not result.approved
        assert result.rejection_code == "KILL_SWITCH"

    def test_non_halted_passes(self, engine, valid_signal, settings, account):
        result = engine.validate(valid_signal, settings, account)
        assert result.approved


# ── CHECK 1: HOLD 시그널 ──────────────────────────────────────────────────────

class TestHoldCheck:
    def test_hold_signal_rejected(self, engine, settings, account):
        signal = _signal(direction="HOLD", take_profit=None, stop_loss=None)
        result = engine.validate(signal, settings, account)
        assert not result.approved
        assert result.rejection_code == "HOLD"


# ── CHECK 2: 자동매매 활성화 ──────────────────────────────────────────────────

class TestTradingActiveCheck:
    def test_inactive_rejected(self, engine, valid_signal, account):
        s = _settings(is_trading_active=False)
        result = engine.validate(valid_signal, s, account)
        assert not result.approved
        assert result.rejection_code == "TRADING_INACTIVE"


# ── CHECK 3: Stop Loss ────────────────────────────────────────────────────────

class TestStopLossCheck:
    def test_none_stop_loss_rejected(self, engine, settings, account):
        signal = _signal(stop_loss=None)
        result = engine.validate(signal, settings, account)
        assert not result.approved
        assert result.rejection_code == "ORDER_003"

    def test_zero_stop_loss_rejected(self, engine, settings, account):
        signal = _signal(stop_loss=Decimal("0"))
        result = engine.validate(signal, settings, account)
        assert not result.approved
        assert result.rejection_code == "ORDER_003"


# ── CHECK 4: R:R ≥ 2.0 ───────────────────────────────────────────────────────

class TestRRRatioCheck:
    def test_rr_below_2_rejected(self, engine, settings, account):
        # entry=67450, tp=68000, sl=66800 → profit=550, loss=650 → RR=0.85
        signal = _signal(take_profit=Decimal("68000"), stop_loss=Decimal("66800"))
        result = engine.validate(signal, settings, account)
        assert not result.approved
        assert result.rejection_code == "ORDER_004"

    def test_rr_exactly_2_approved(self, engine, settings, account):
        # entry=67450, tp=68750 (+1300), sl=66800 (-650) → RR=2.0
        # leverage=20: margin = (50/650)×67450/20 = $256 = 2.56% ✓
        signal = _signal(take_profit=Decimal("68750"), stop_loss=Decimal("66800"))
        result = engine.validate(signal, settings, account)
        assert result.approved

    def test_short_rr_calculation(self, engine, settings, account):
        # SHORT: entry=67450, tp=65250 (profit=2200), sl=68550 (loss=1100) → RR=2.0
        # leverage=20: margin = (50/1100)×67450/20 = $153 = 1.53% ✓
        signal = _signal(
            direction="SHORT",
            take_profit=Decimal("65250"),
            stop_loss=Decimal("68550"),
        )
        result = engine.validate(signal, settings, account)
        assert result.approved


# ── CHECK 5: 신뢰도 ≥ 60% ────────────────────────────────────────────────────

class TestConfidenceCheck:
    def test_low_confidence_rejected(self, engine, settings, account):
        signal = _signal(confidence=0.59)
        result = engine.validate(signal, settings, account)
        assert not result.approved
        assert result.rejection_code == "LOW_CONFIDENCE"

    def test_exactly_60pct_approved(self, engine, settings, account):
        signal = _signal(confidence=0.60)
        result = engine.validate(signal, settings, account)
        assert result.approved


# ── CHECK 7: 일일 손실 한도 ───────────────────────────────────────────────────

class TestDailyLossCheck:
    def test_daily_loss_halt(self, engine, settings):
        """일일 손실 한도 초과 시 거부 + account halt.
        settings: daily_loss_limit_pct=0.05 → 한도 = 5% × $10,000 = $500
        """
        from agents.paper_trading.models import PaperTradeRecord
        from datetime import timezone

        acc = _account(10000)
        now = datetime.now(timezone.utc)

        # 오늘 손실 $500 = 5% (정확히 한도 도달)
        loss_record = PaperTradeRecord(
            id="t1", position_id="p1", user_id="u1",
            coin="BTC", direction="LONG",
            entry_price=Decimal("67450"), close_price=Decimal("66800"),
            quantity=Decimal("0.076"), leverage=20,
            gross_pnl=Decimal("-49.40"), fee=Decimal("2.10"),
            net_pnl=Decimal("-500"),  # 정확히 한도(5% of 10000)
            pnl_pct=Decimal("-5"), duration_seconds=3600,
            close_reason="sl_hit", opened_at=now, closed_at=now,
        )
        acc.add_trade(loss_record)

        result = engine.validate(_signal(), settings, acc)
        assert not result.approved
        assert result.rejection_code == "ORDER_001"

    def test_below_daily_limit_approved(self, engine, settings, account):
        result = engine.validate(_signal(), settings, account)
        assert result.approved


# ── CHECK 9: 연속 손실 쿨다운 ────────────────────────────────────────────────

class TestConsecutiveLossCheck:
    def test_cooldown_state_rejected(self, engine, settings):
        acc = _account()
        acc.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=25)
        result = engine.validate(_signal(), settings, acc)
        assert not result.approved
        assert result.rejection_code == "CONSEC_LOSS"

    def test_3_consecutive_triggers_cooldown(self, engine, settings):
        from agents.paper_trading.models import PaperTradeRecord
        acc = _account()
        now = datetime.now(timezone.utc)

        for i in range(3):
            acc.add_trade(PaperTradeRecord(
                id=f"t{i}", position_id=f"p{i}", user_id="u1",
                coin="BTC", direction="LONG",
                entry_price=Decimal("67450"), close_price=Decimal("66800"),
                quantity=Decimal("0.001"), leverage=5,
                gross_pnl=Decimal("-0.65"), fee=Decimal("0.05"),
                net_pnl=Decimal("-0.70"),
                pnl_pct=Decimal("-0.70"), duration_seconds=60,
                close_reason="sl_hit", opened_at=now, closed_at=now,
            ))

        result = engine.validate(_signal(), settings, acc)
        assert not result.approved
        assert result.rejection_code == "CONSEC_LOSS"
        assert acc.in_cooldown

    def test_5_consecutive_triggers_halt(self, engine, settings):
        from agents.paper_trading.models import PaperTradeRecord
        acc = _account()
        now = datetime.now(timezone.utc)

        for i in range(5):
            acc.add_trade(PaperTradeRecord(
                id=f"t{i}", position_id=f"p{i}", user_id="u1",
                coin="BTC", direction="LONG",
                entry_price=Decimal("67450"), close_price=Decimal("66800"),
                quantity=Decimal("0.001"), leverage=5,
                gross_pnl=Decimal("-0.65"), fee=Decimal("0.05"),
                net_pnl=Decimal("-0.70"),
                pnl_pct=Decimal("-0.70"), duration_seconds=60,
                close_reason="sl_hit", opened_at=now, closed_at=now,
            ))

        result = engine.validate(_signal(), settings, acc)
        assert not result.approved
        assert result.rejection_code == "CONSEC_LOSS"
        assert acc.is_halted


# ── CHECK 10: 동시 포지션 한도 ───────────────────────────────────────────────

class TestPositionCountCheck:
    def test_position_limit_exceeded(self, engine, settings):
        """Pro 플랜 최대 5개 포지션 초과 시 거부."""
        from agents.paper_trading.models import PaperPosition

        acc = _account()
        for i in range(5):
            pos = PaperPosition(
                id=f"pos-{i}", user_id="u1",
                coin=f"COIN{i}", symbol=f"COIN{i}USDT",
                direction="LONG",
                entry_price=Decimal("100"), quantity=Decimal("1"),
                original_quantity=Decimal("1"), leverage=5,
                take_profit=Decimal("110"), stop_loss=Decimal("95"),
                liquidation_price=Decimal("85"),
                margin_used=Decimal("100"), original_margin=Decimal("100"),
                max_loss_usdt=Decimal("10"), max_profit_usdt=Decimal("20"),
                original_risk_usdt=Decimal("10"),
            )
            acc.add_position(pos)

        result = engine.validate(_signal(), settings, acc)
        assert not result.approved
        assert result.rejection_code == "ORDER_002"

    def test_free_plan_1_position_limit(self, engine):
        from agents.paper_trading.models import PaperPosition

        s = _settings(plan="free", max_concurrent_positions=1)
        acc = _account()

        pos = PaperPosition(
            id="pos-1", user_id="u1", coin="ETH", symbol="ETHUSDT",
            direction="LONG", entry_price=Decimal("3500"),
            quantity=Decimal("0.1"), original_quantity=Decimal("0.1"),
            leverage=5, take_profit=Decimal("3700"), stop_loss=Decimal("3400"),
            liquidation_price=Decimal("2900"), margin_used=Decimal("50"),
            original_margin=Decimal("50"), max_loss_usdt=Decimal("10"),
            max_profit_usdt=Decimal("20"), original_risk_usdt=Decimal("10"),
        )
        acc.add_position(pos)

        result = engine.validate(_signal(), s, acc)
        assert not result.approved
        assert result.rejection_code == "ORDER_002"


# ── CHECK 12: 포지션 사이징 ──────────────────────────────────────────────────

class TestSizingCheck:
    def test_approved_result_has_sizing_info(self, engine, settings, account):
        result = engine.validate(_signal(), settings, account)
        assert result.approved
        assert result.quantity > 0
        assert result.final_leverage is not None
        assert result.margin_required_usdt is not None
        assert result.max_loss_usdt is not None
        assert result.rr_ratio is not None

    def test_leverage_capped_by_plan(self, engine, account):
        # Pro 플랜 최대 10x, AI가 25x 추천해도 10x로 캡
        # risk_per_trade=0.005: margin = (50/650)×67450/10 = $519 = 5.19% ✓
        s = _settings(plan="pro", max_leverage=10, risk_per_trade=0.005)
        signal = _signal(leverage=25)
        result = engine.validate(signal, s, account)
        assert result.approved
        assert result.final_leverage == 10
        assert any("LEVERAGE_CAPPED" in w for w in result.warnings)

    def test_insufficient_balance_rejected(self, engine, settings):
        # 잔고 $10, 최소 주문금액 $5 → sizing 실패
        acc = _account(10)
        result = engine.validate(_signal(), settings, acc)
        assert not result.approved

    def test_sizing_info_matches_trading_rules(self, engine, settings, account):
        """TRADING_RULES.md §7.1 공식 검증 (risk_per_trade=0.005, leverage=20):
        risk_amount = 10000 × 0.005 = $50
        sl_distance = |67450 - 66800| = $650
        quantity    = 50 / 650 = 0.076923 → lot round → 0.076 BTC
        max_loss    = 0.076 × 650 = $49.40
        margin      = 0.076 × 67450 / 20 = $256.31 = 2.56% ✓
        """
        result = engine.validate(_signal(), settings, account)
        assert result.approved
        # max_loss = quantity × sl_distance ≈ risk_amount (lot_size 반올림 오차 허용)
        expected_risk = Decimal("10000") * Decimal("0.005")  # $50
        assert result.max_loss_usdt < expected_risk  # lot_size 내림으로 약간 작음
        assert result.max_loss_usdt > expected_risk * Decimal("0.90")  # 10% 이내 오차
