"""
PositionManager 단위 테스트 — 포지션 생명주기 커버리지.

테스트 항목:
  - LONG/SHORT 포지션 오픈
  - TP/SL 도달 감지 (update_price)
  - 전량 청산 (close_position)
  - 부분 청산 (partial_close)
  - DCA (apply_dca)
  - 청산가 계산
  - PnL / Fee 계산 정확성
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.risk.models import RawSignal, ValidationResult
from agents.paper_trading.models import PaperUserSettings, TAKER_FEE_RATE
from agents.paper_trading.position_manager import PositionManager
from agents.paper_trading.state import PaperAccountState


# ── 공통 픽스처 ────────────────────────────────────────────────────────────────

@pytest.fixture
def pm() -> PositionManager:
    return PositionManager()


@pytest.fixture
def settings() -> PaperUserSettings:
    return PaperUserSettings(user_id="u1", plan="pro", risk_profile="moderate")


@pytest.fixture
def account() -> PaperAccountState:
    return PaperAccountState(
        user_id="u1",
        _balance=Decimal("10000"),
        initial_balance=Decimal("10000"),
    )


def _validation(
    qty="0.076",     # 0.005 × 10000 / 650 = 0.07692 → lot → 0.076 BTC
    lev=20,
    margin="256.31", # 0.076 × 67450 / 20
    max_loss="49.40", # 0.076 × 650
    max_profit="133.00",  # 0.076 × 1750
) -> ValidationResult:
    return ValidationResult(
        approved=True,
        quantity=Decimal(qty),
        final_leverage=lev,
        margin_required_usdt=Decimal(margin),
        max_loss_usdt=Decimal(max_loss),
        max_profit_usdt=Decimal(max_profit),
        rr_ratio=Decimal("2.69"),
    )


def _long_signal() -> RawSignal:
    # R:R = 1750/650 = 2.69 ✓
    # leverage=20: margin = (50/650)×67450/20 = $256 = 2.56% ✓
    return RawSignal(
        direction="LONG", coin="BTC", symbol="BTCUSDT",
        confidence=0.85, leverage=20,
        entry_price=Decimal("67450"),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66800"),
    )


def _short_signal() -> RawSignal:
    # R:R = 2200/1100 = 2.0 ✓
    # leverage=20: margin = (50/1100)×67450/20 = $153 ✓
    return RawSignal(
        direction="SHORT", coin="BTC", symbol="BTCUSDT",
        confidence=0.80, leverage=20,
        entry_price=Decimal("67450"),
        take_profit=Decimal("65250"),
        stop_loss=Decimal("68550"),
    )


# ── 포지션 오픈 ────────────────────────────────────────────────────────────────

class TestOpenPosition:
    def test_long_position_opened(self, pm, account, settings):
        signal = _long_signal()
        validation = _validation()
        pos = pm.open_position(signal, validation, account, settings)

        assert pos.direction == "LONG"
        assert pos.coin == "BTC"
        assert pos.entry_price == Decimal("67450")
        assert pos.take_profit == Decimal("69200")
        assert pos.stop_loss == Decimal("66800")
        assert pos.leverage == 20  # _long_signal() uses leverage=20
        assert pos.status == "open"
        assert pos.is_open is True
        assert pos in account.open_positions.values()

    def test_short_position_opened(self, pm, account, settings):
        signal = _short_signal()
        validation = _validation()
        pos = pm.open_position(signal, validation, account, settings)
        assert pos.direction == "SHORT"

    def test_entry_fee_deducted_from_balance(self, pm, account, settings):
        signal = _long_signal()
        validation = _validation(qty="0.022", margin="307.69")
        initial_balance = account.balance

        pm.open_position(signal, validation, account, settings)

        expected_entry_fee = Decimal("0.022") * Decimal("67450") * TAKER_FEE_RATE
        assert account.balance == initial_balance - expected_entry_fee

    def test_liquidation_price_long(self, pm, account, settings):
        signal = _long_signal()
        validation = _validation(lev=10)
        pos = pm.open_position(signal, validation, account, settings)
        # LONG liq = entry × (1 - 1/lev + 0.004)
        # = 67450 × (1 - 0.1 + 0.004) = 67450 × 0.904 = 60994.8
        assert pos.liquidation_price < pos.entry_price
        assert pos.liquidation_price > 0

    def test_liquidation_price_short(self, pm, account, settings):
        signal = _short_signal()
        validation = _validation(lev=10)
        pos = pm.open_position(signal, validation, account, settings)
        # SHORT liq = entry × (1 + 1/lev - 0.004)
        assert pos.liquidation_price > pos.entry_price


# ── TP/SL 감지 ─────────────────────────────────────────────────────────────────

class TestUpdatePrice:
    def test_long_tp_hit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("69200"))
        assert result == "tp_hit"

    def test_long_tp_above_price_no_hit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("68000"))
        assert result is None

    def test_long_sl_hit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("66800"))
        assert result == "sl_hit"

    def test_long_sl_above_threshold_no_hit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("66801"))
        assert result is None

    def test_short_tp_hit(self, pm, account, settings):
        pos = pm.open_position(_short_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("65250"))  # _short_signal() tp=65250
        assert result == "tp_hit"

    def test_short_sl_hit(self, pm, account, settings):
        pos = pm.open_position(_short_signal(), _validation(), account, settings)
        result = pm.update_price(pos, Decimal("68550"))
        assert result == "sl_hit"

    def test_closed_position_returns_none(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        pos.status = "closed"
        result = pm.update_price(pos, Decimal("99999"))
        assert result is None

    def test_price_updates_current_price(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        pm.update_price(pos, Decimal("68000"))
        assert pos.current_price == Decimal("68000")


# ── 전량 청산 ──────────────────────────────────────────────────────────────────

class TestClosePosition:
    def test_close_at_tp_profit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        balance_before = account.balance

        record = pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)

        assert record.close_reason == "tp_hit"
        assert record.net_pnl > 0
        # 잔고 증가 (net_pnl > 0)
        assert account.balance > balance_before

    def test_close_at_sl_loss(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        balance_before = account.balance

        record = pm.close_position(pos, Decimal("66800"), "sl_hit", account, settings)

        assert record.close_reason == "sl_hit"
        assert record.net_pnl < 0
        assert account.balance < balance_before

    def test_position_status_closed_after_close(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)
        assert pos.status == "closed"
        assert pos.closed_at is not None
        assert pos.close_reason == "tp_hit"

    def test_position_removed_from_account(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        assert len(account.open_positions) == 1
        pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)
        assert len(account.open_positions) == 0

    def test_trade_record_added_to_history(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)
        assert len(account.trade_history) == 1

    def test_pnl_calculation_accuracy(self, pm, account, settings):
        """
        PnL 계산 정확성 검증:
        entry=67450, close=69200, qty=0.076 → LONG
        gross_pnl = (69200 - 67450) × 0.076 = 1750 × 0.076 = $133.00
        exit_fee  = 0.076 × 69200 × 0.0004 = $2.104
        net_pnl   ≈ $133.00 - $2.104 = $130.90 (청산분만, 진입분은 이미 차감)
        """
        pos = pm.open_position(_long_signal(), _validation(qty="0.076"), account, settings)
        record = pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)

        expected_gross = (Decimal("69200") - Decimal("67450")) * Decimal("0.076")
        assert record.gross_pnl == expected_gross.quantize(Decimal("0.01"))
        assert record.net_pnl < record.gross_pnl  # 수수료 차감됨

    def test_short_close_profit_at_tp(self, pm, account, settings):
        """SHORT 포지션: 가격 하락 시 수익."""
        pos = pm.open_position(_short_signal(), _validation(qty="0.022"), account, settings)
        balance_before = account.balance

        record = pm.close_position(pos, Decimal("65700"), "tp_hit", account, settings)
        assert record.net_pnl > 0
        assert account.balance > balance_before

    def test_cannot_close_already_closed(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(), account, settings)
        pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)
        with pytest.raises(AssertionError):
            pm.close_position(pos, Decimal("69200"), "manual", account, settings)


# ── 부분 청산 ──────────────────────────────────────────────────────────────────

class TestPartialClose:
    def test_50pct_partial_close(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        original_qty = pos.quantity

        updated_pos, record = pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)

        # 수량이 절반으로 줄었는지
        assert updated_pos.quantity == original_qty - record.quantity
        assert record.is_partial is True
        assert record.close_reason == "partial"

    def test_partial_close_updates_status(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)
        assert pos.status == "partially_closed"

    def test_partial_close_still_open(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)
        assert pos.is_open is True
        assert pos.id in account.open_positions

    def test_partial_close_adds_to_history(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)
        assert len(account.trade_history) == 1

    def test_partial_close_balance_increases_on_profit(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        balance_before = account.balance
        pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)
        # 가격이 entry보다 높으므로 수익
        assert account.balance > balance_before

    def test_partial_close_then_full_close(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        pm.partial_close(pos, Decimal("68000"), 0.5, account, settings)
        record = pm.close_position(pos, Decimal("69200"), "tp_hit", account, settings)

        assert record.close_reason == "tp_hit"
        assert pos.status == "closed"
        assert len(account.trade_history) == 2

    def test_invalid_ratio_raises(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022"), account, settings)
        with pytest.raises((AssertionError, ValueError)):
            pm.partial_close(pos, Decimal("68000"), 1.0, account, settings)
        with pytest.raises((AssertionError, ValueError)):
            pm.partial_close(pos, Decimal("68000"), 0.0, account, settings)


# ── DCA ────────────────────────────────────────────────────────────────────────

class TestDCA:
    def test_dca_increases_quantity(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022", margin="307"), account, settings)
        original_qty = pos.quantity

        dca_signal = RawSignal(
            direction="LONG", coin="BTC", symbol="BTCUSDT",
            confidence=0.80, leverage=5,
            entry_price=Decimal("67000"),
            take_profit=Decimal("69200"),
            stop_loss=Decimal("66800"),
        )
        dca_validation = _validation(qty="0.015", margin="200", max_loss="130", max_profit="350")

        updated = pm.apply_dca(pos, dca_signal, dca_validation, account, settings)

        assert updated.quantity > original_qty
        assert updated.dca_count == 1

    def test_dca_recalculates_avg_entry(self, pm, account, settings):
        """DCA 후 평균 진입가 재계산 검증 (§8.3)"""
        pos = pm.open_position(_long_signal(), _validation(qty="1.0", margin="307"), account, settings)
        # 처음 qty=1.0 @ 67450

        dca_signal = RawSignal(
            direction="LONG", coin="BTC", symbol="BTCUSDT",
            confidence=0.80, leverage=5,
            entry_price=Decimal("66000"),  # 낮은 가격에 DCA
            take_profit=Decimal("69200"),
            stop_loss=Decimal("65500"),
        )
        dca_validation = ValidationResult(
            approved=True, quantity=Decimal("1.0"),
            final_leverage=5, margin_required_usdt=Decimal("280"),
            max_loss_usdt=Decimal("200"), max_profit_usdt=Decimal("400"),
            rr_ratio=Decimal("2.0"),
        )

        updated = pm.apply_dca(pos, dca_signal, dca_validation, account, settings)

        # avg = (1.0 × 67450 + 1.0 × 66000) / 2.0 = 66725
        assert updated.entry_price == Decimal("66725")
        assert updated.quantity == Decimal("2.0")

    def test_dca_increases_margin(self, pm, account, settings):
        pos = pm.open_position(_long_signal(), _validation(qty="0.022", margin="307"), account, settings)
        original_margin = pos.margin_used
        original_dca_count = pos.dca_count

        dca_validation = ValidationResult(
            approved=True, quantity=Decimal("0.015"),
            final_leverage=5, margin_required_usdt=Decimal("200"),
            max_loss_usdt=Decimal("130"), max_profit_usdt=Decimal("350"),
            rr_ratio=Decimal("2.0"),
        )
        dca_signal = RawSignal(
            direction="LONG", coin="BTC", symbol="BTCUSDT",
            confidence=0.80, leverage=5,
            entry_price=Decimal("67000"),
            take_profit=Decimal("69200"),
            stop_loss=Decimal("66800"),
        )

        pm.apply_dca(pos, dca_signal, dca_validation, account, settings)

        assert pos.margin_used > original_margin
        assert pos.dca_count == original_dca_count + 1


# ── 청산가 계산 ────────────────────────────────────────────────────────────────

class TestLiquidationPrice:
    @pytest.mark.parametrize("leverage,expected_factor", [
        (5,  Decimal("0.8040")),   # 1 - 0.2 + 0.004 = 0.804
        (10, Decimal("0.9040")),   # 1 - 0.1 + 0.004 = 0.904
        (20, Decimal("0.9540")),   # 1 - 0.05 + 0.004 = 0.954
    ])
    def test_long_liquidation_price(self, pm, leverage, expected_factor):
        entry = Decimal("67450")
        liq = pm._calc_liquidation_price("LONG", entry, leverage)
        expected = (entry * expected_factor).quantize(Decimal("0.01"))
        assert abs(liq - expected) < Decimal("1")

    @pytest.mark.parametrize("leverage,expected_factor", [
        (5,  Decimal("1.1960")),   # 1 + 0.2 - 0.004 = 1.196
        (10, Decimal("1.0960")),   # 1 + 0.1 - 0.004 = 1.096
        (20, Decimal("1.0460")),   # 1 + 0.05 - 0.004 = 1.046
    ])
    def test_short_liquidation_price(self, pm, leverage, expected_factor):
        entry = Decimal("67450")
        liq = pm._calc_liquidation_price("SHORT", entry, leverage)
        expected = (entry * expected_factor).quantize(Decimal("0.01"))
        assert abs(liq - expected) < Decimal("1")
