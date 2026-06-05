"""
PaperTradingEngine 통합 테스트 — 완전한 거래 사이클 검증.

테스트 항목:
  1. LONG 시그널 → TP 도달 → 청산 (수익)
  2. SHORT 시그널 → SL 도달 → 청산 (손실)
  3. 시그널 제출 → 수동 청산
  4. 부분 청산 후 TP 도달
  5. 반전 포지션 (close_existing → 신규)
  6. DCA 적용
  7. 일일 손실 한도 도달 → Halt
  8. 연속 손실 → 쿨다운
  9. 포지션 한도 초과 → 거부
  10. get_summary() 정확성
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agents.risk.models import RawSignal
from agents.paper_trading.engine import PaperTradingEngine
from agents.paper_trading.models import PaperUserSettings


# ── 픽스처 ────────────────────────────────────────────────────────────────────

def _settings(**kwargs) -> PaperUserSettings:
    # risk_per_trade=0.005 (0.5%), leverage=20 (Elite) 사용 이유:
    # BTC: quantity = (10000×0.005)/650 = 0.076 BTC
    #      margin   = 0.076 × 67450 / 20 = $256 = 2.56% ≤ 20% 한도 ✓
    # ETH: quantity = (10000×0.005)/100 = 0.50 ETH
    #      margin   = 0.50 × 3500 / 20 = $87.5 = 0.875% ✓
    defaults = dict(
        user_id="tester",
        plan="elite",
        risk_profile="aggressive",
        risk_per_trade=0.005,
        max_leverage=20,
        max_concurrent_positions=5,
        daily_loss_limit_pct=0.05,
        weekly_loss_limit_pct=0.15,
    )
    defaults.update(kwargs)
    return PaperUserSettings(**defaults)


def _engine(balance: float = 10000.0, **kwargs) -> PaperTradingEngine:
    return PaperTradingEngine(
        initial_balance=Decimal(str(balance)),
        settings=_settings(**kwargs),
    )


def _btc_long(entry="67450", tp="69200", sl="66800", conf=0.85, lev=20) -> RawSignal:
    # R:R = (69200-67450)/(67450-66800) = 1750/650 = 2.69 ✓
    return RawSignal(
        direction="LONG", coin="BTC", symbol="BTCUSDT",
        confidence=conf, leverage=lev,
        entry_price=Decimal(entry),
        take_profit=Decimal(tp),
        stop_loss=Decimal(sl),
    )


def _btc_short(entry="67450", tp="65250", sl="68550", conf=0.80, lev=20) -> RawSignal:
    # R:R = (67450-65250)/(68550-67450) = 2200/1100 = 2.0 ✓
    return RawSignal(
        direction="SHORT", coin="BTC", symbol="BTCUSDT",
        confidence=conf, leverage=lev,
        entry_price=Decimal(entry),
        take_profit=Decimal(tp),
        stop_loss=Decimal(sl),
    )


def _eth_long(entry="3500", tp="3700", sl="3400", conf=0.80, lev=20) -> RawSignal:
    # R:R = (3700-3500)/(3500-3400) = 200/100 = 2.0 ✓
    return RawSignal(
        direction="LONG", coin="ETH", symbol="ETHUSDT",
        confidence=conf, leverage=lev,
        entry_price=Decimal(entry),
        take_profit=Decimal(tp),
        stop_loss=Decimal(sl),
    )


# ── 시나리오 1: LONG → TP 청산 (수익) ─────────────────────────────────────────

class TestLongTPScenario:
    def test_long_open_and_tp_close(self):
        engine = _engine()
        result = engine.submit_signal(_btc_long())
        assert result.accepted
        assert result.position is not None

        pos_id = result.position.id
        initial_balance = engine.account.balance

        # TP 가격으로 tick
        closed = engine.tick("BTC", Decimal("69200"))

        assert len(closed) == 1
        assert closed[0].close_reason == "tp_hit"
        assert closed[0].net_pnl > 0
        # 잔고가 증가했는지
        assert engine.account.balance > initial_balance
        # 포지션이 없어졌는지
        assert len(engine.get_open_positions()) == 0
        assert len(engine.get_trade_history()) == 1

    def test_price_below_tp_no_close(self):
        engine = _engine()
        engine.submit_signal(_btc_long())

        closed = engine.tick("BTC", Decimal("68000"))
        assert len(closed) == 0
        assert len(engine.get_open_positions()) == 1


# ── 시나리오 2: SHORT → SL 청산 (손실) ───────────────────────────────────────

class TestShortSLScenario:
    def test_short_open_and_sl_hit(self):
        engine = _engine()
        result = engine.submit_signal(_btc_short())
        assert result.accepted

        initial_balance = engine.account.balance

        closed = engine.tick("BTC", Decimal("68550"))  # sl=68550

        assert len(closed) == 1
        assert closed[0].close_reason == "sl_hit"
        assert closed[0].net_pnl < 0
        assert engine.account.balance < initial_balance

    def test_short_tp_profit(self):
        engine = _engine()
        engine.submit_signal(_btc_short())
        initial_balance = engine.account.balance

        closed = engine.tick("BTC", Decimal("65250"))  # tp=65250
        assert len(closed) == 1
        assert closed[0].net_pnl > 0
        assert engine.account.balance > initial_balance


# ── 시나리오 3: 수동 청산 ──────────────────────────────────────────────────────

class TestManualClose:
    def test_manual_close(self):
        engine = _engine()
        result = engine.submit_signal(_btc_long())
        pos_id = result.position.id

        record = engine.close_position(pos_id, Decimal("68000"))
        assert record is not None
        assert record.close_reason == "manual"
        assert len(engine.get_open_positions()) == 0

    def test_manual_close_nonexistent_returns_none(self):
        engine = _engine()
        record = engine.close_position("nonexistent-id", Decimal("68000"))
        assert record is None

    def test_manual_close_adds_to_history(self):
        engine = _engine()
        result = engine.submit_signal(_btc_long())
        engine.close_position(result.position.id, Decimal("68000"))
        assert len(engine.get_trade_history()) == 1


# ── 시나리오 4: 부분 청산 후 TP ──────────────────────────────────────────────

class TestPartialThenTP:
    def test_partial_close_then_tp(self):
        engine = _engine()
        result = engine.submit_signal(_btc_long())
        pos_id = result.position.id

        # 50% 부분 청산
        partial_result = engine.partial_close(pos_id, Decimal("68000"), ratio=0.5)
        assert partial_result is not None
        updated_pos, partial_record = partial_result
        assert partial_record.is_partial is True
        assert len(engine.get_open_positions()) == 1  # 포지션 유지

        # 남은 50%가 TP 도달
        closed = engine.tick("BTC", Decimal("69200"))
        assert len(closed) == 1
        assert closed[0].close_reason == "tp_hit"
        assert len(engine.get_open_positions()) == 0
        assert len(engine.get_trade_history()) == 2  # partial + full

    def test_partial_close_profit_larger_at_higher_price(self):
        engine = _engine()
        result = engine.submit_signal(_btc_long())
        pos_id = result.position.id

        _, r1 = engine.partial_close(pos_id, Decimal("68000"), ratio=0.5)
        assert r1.gross_pnl > 0


# ── 시나리오 5: 반전 포지션 (Long → Short) ────────────────────────────────────

class TestReversePosition:
    def test_reverse_long_to_short(self):
        engine = _engine()
        # LONG 먼저 오픈
        r1 = engine.submit_signal(_btc_long())
        assert r1.accepted
        long_pos_id = r1.position.id

        # SHORT 시그널 제출 (기존 LONG 청산 후 SHORT 오픈)
        r2 = engine.submit_signal(_btc_short())

        assert r2.accepted
        # close_existing 처리됨
        assert r2.closed_trade is not None
        # 이제 SHORT 포지션
        assert r2.position is not None
        assert r2.position.direction == "SHORT"
        # 이전 LONG 포지션은 없어졌는지
        assert len(engine.get_open_positions()) == 1
        assert engine.get_open_positions()[0].direction == "SHORT"


# ── 시나리오 6: DCA ────────────────────────────────────────────────────────────

class TestDCAScenario:
    def test_dca_same_direction(self):
        engine = _engine()
        r1 = engine.submit_signal(_btc_long())
        assert r1.accepted
        original_qty = r1.position.quantity

        # 같은 방향 BTC LONG 재제출 → DCA
        r2 = engine.submit_signal(_btc_long(entry="67000", tp="69200", sl="66800"))
        assert r2.accepted
        assert r2.pre_action == "dca"
        # 포지션은 여전히 1개
        assert len(engine.get_open_positions()) == 1
        # 수량이 증가했는지
        updated_pos = engine.get_open_positions()[0]
        assert updated_pos.quantity > original_qty
        assert updated_pos.dca_count == 1


# ── 시나리오 7: 일일 손실 한도 → Halt ─────────────────────────────────────────

class TestDailyLossHalt:
    def test_halt_after_daily_loss_limit(self):
        """일일 손실 한도 도달 시 Halt + 새 시그널 거부.
        settings: daily_loss_limit_pct=0.05 → 한도 = 5% × $10,000 = $500
        """
        from agents.paper_trading.models import PaperTradeRecord
        from datetime import datetime, timezone

        engine = _engine(balance=10000)
        now = datetime.now(timezone.utc)

        # 일일 손실 $500 = 5% (정확히 한도 도달)
        engine.account.add_trade(PaperTradeRecord(
            id="t1", position_id="p1", user_id="tester",
            coin="BTC", direction="LONG",
            entry_price=Decimal("67450"), close_price=Decimal("66800"),
            quantity=Decimal("0.076"), leverage=20,
            gross_pnl=Decimal("-49.40"), fee=Decimal("2.10"),
            net_pnl=Decimal("-500"),  # 5% of 10000 = 한도 도달
            pnl_pct=Decimal("-5"), duration_seconds=3600,
            close_reason="sl_hit", opened_at=now, closed_at=now,
        ))

        result = engine.submit_signal(_btc_long())
        assert not result.accepted
        assert result.rejection_code == "ORDER_001"

    def test_manual_resume_after_halt(self):
        engine = _engine()
        engine.halt("test")
        assert not engine.submit_signal(_btc_long()).accepted

        engine.resume()
        assert engine.submit_signal(_btc_long()).accepted


# ── 시나리오 8: 연속 손실 → 쿨다운 ──────────────────────────────────────────

class TestConsecutiveLossCooldown:
    def test_3_losses_trigger_cooldown(self):
        from agents.paper_trading.models import PaperTradeRecord
        from datetime import datetime, timezone

        engine = _engine()
        now = datetime.now(timezone.utc)

        for i in range(3):
            engine.account.add_trade(PaperTradeRecord(
                id=f"t{i}", position_id=f"p{i}", user_id="tester",
                coin="BTC", direction="LONG",
                entry_price=Decimal("67450"), close_price=Decimal("66800"),
                quantity=Decimal("0.001"), leverage=5,
                gross_pnl=Decimal("-0.65"), fee=Decimal("0.05"),
                net_pnl=Decimal("-0.70"),
                pnl_pct=Decimal("-0.70"), duration_seconds=60,
                close_reason="sl_hit", opened_at=now, closed_at=now,
            ))

        result = engine.submit_signal(_btc_long())
        assert not result.accepted
        assert result.rejection_code == "CONSEC_LOSS"
        assert engine.account.in_cooldown


# ── 시나리오 9: 포지션 한도 초과 ─────────────────────────────────────────────

class TestPositionLimit:
    def test_max_positions_exceeded(self):
        """Elite 플랜이지만 max_concurrent_positions=2로 제한 시 3번째 거부."""
        engine = _engine(max_concurrent_positions=2)

        r1 = engine.submit_signal(_btc_long())
        assert r1.accepted
        r2 = engine.submit_signal(_eth_long())
        assert r2.accepted
        # 3번째 시도 (다른 코인 — 포지션 한도 초과)
        r3 = engine.submit_signal(RawSignal(
            direction="LONG", coin="SOL", symbol="SOLUSDT",
            confidence=0.80, leverage=20,
            entry_price=Decimal("150"),
            take_profit=Decimal("200"),   # profit=50
            stop_loss=Decimal("125"),     # loss=25, R:R=2.0 ✓
        ))
        assert not r3.accepted
        assert r3.rejection_code == "ORDER_002"


# ── 시나리오 10: HOLD 시그널 ──────────────────────────────────────────────────

class TestHoldSignal:
    def test_hold_signal_not_accepted(self):
        engine = _engine()
        signal = RawSignal(
            direction="HOLD", coin="BTC", symbol="BTCUSDT",
            confidence=0.55, leverage=5,
            entry_price=Decimal("67450"),
            take_profit=None,
            stop_loss=None,
        )
        result = engine.submit_signal(signal)
        assert not result.accepted
        assert result.rejection_code == "HOLD"


# ── get_summary() 정확성 ──────────────────────────────────────────────────────

class TestGetSummary:
    def test_empty_summary(self):
        engine = _engine()
        summary = engine.get_summary()
        assert summary["performance"]["total_closed_trades"] == 0
        assert summary["performance"]["win_rate"] == 0
        assert summary["account"]["balance"] == 10000.0

    def test_summary_after_win(self):
        engine = _engine()
        engine.submit_signal(_btc_long())
        engine.tick("BTC", Decimal("69200"))  # TP hit

        summary = engine.get_summary()
        assert summary["performance"]["total_closed_trades"] == 1
        assert summary["performance"]["win_count"] == 1
        assert summary["performance"]["loss_count"] == 0
        assert summary["performance"]["win_rate"] == 1.0
        assert summary["performance"]["total_pnl"] > 0

    def test_summary_after_loss(self):
        engine = _engine()
        engine.submit_signal(_btc_long())
        engine.tick("BTC", Decimal("66800"))  # SL hit

        summary = engine.get_summary()
        assert summary["performance"]["win_count"] == 0
        assert summary["performance"]["loss_count"] == 1
        assert summary["performance"]["total_pnl"] < 0

    def test_summary_open_positions(self):
        engine = _engine()
        engine.submit_signal(_btc_long())

        summary = engine.get_summary()
        assert len(summary["open_positions"]) == 1
        assert summary["open_positions"][0]["coin"] == "BTC"
        assert summary["open_positions"][0]["direction"] == "LONG"

    def test_unrealized_pnl_in_summary(self):
        engine = _engine()
        engine.submit_signal(_btc_long())
        engine.update_prices({"BTC": Decimal("68000")})  # unrealized profit

        summary = engine.get_summary()
        assert summary["performance"]["unrealized_pnl"] > 0


# ── update_prices (가격 업데이트, TP/SL 없음) ────────────────────────────────

class TestUpdatePrices:
    def test_update_prices_no_close(self):
        engine = _engine()
        engine.submit_signal(_btc_long())
        engine.update_prices({"BTC": Decimal("68000")})

        assert len(engine.get_open_positions()) == 1
        pos = engine.get_open_positions()[0]
        assert pos.current_price == Decimal("68000")
        assert pos.unrealized_pnl > 0

    def test_update_prices_multiple_coins(self):
        engine = _engine()
        engine.submit_signal(_btc_long())
        engine.submit_signal(_eth_long())
        engine.update_prices({"BTC": Decimal("68000"), "ETH": Decimal("3600")})

        positions = {p.coin: p for p in engine.get_open_positions()}
        assert positions["BTC"].current_price == Decimal("68000")
        assert positions["ETH"].current_price == Decimal("3600")


# ── 복합 시나리오: 완전한 거래 세션 ──────────────────────────────────────────

class TestCompleteSession:
    def test_complete_trading_session(self):
        """
        완전한 세션:
        1. BTC LONG 오픈
        2. 50% 부분 청산 (수익 실현)
        3. TP 도달 (나머지 청산)
        4. ETH SHORT 오픈
        5. SL 도달 (손실)
        6. 최종 요약 확인
        """
        engine = _engine(balance=10000)

        # 1. BTC LONG
        r = engine.submit_signal(_btc_long())
        assert r.accepted
        btc_pos_id = r.position.id

        # 2. 50% 부분 청산 ($68,000)
        partial = engine.partial_close(btc_pos_id, Decimal("68000"), 0.5)
        assert partial is not None
        _, partial_record = partial
        assert partial_record.net_pnl > 0

        # 3. TP 도달 ($69,200)
        closed = engine.tick("BTC", Decimal("69200"))
        assert len(closed) == 1
        assert closed[0].net_pnl > 0

        # 4. ETH SHORT
        r2 = engine.submit_signal(_eth_long())
        assert r2.accepted

        # 5. ETH SL 도달 (sl=3400)
        eth_closed = engine.tick("ETH", Decimal("3400"))
        assert len(eth_closed) == 1
        assert eth_closed[0].net_pnl < 0

        # 6. 최종 요약
        summary = engine.get_summary()
        assert summary["performance"]["total_closed_trades"] == 2  # BTC full + ETH (partial은 별도)
        assert summary["performance"]["win_count"] == 1  # BTC TP
        assert summary["performance"]["loss_count"] == 1  # ETH SL
        assert len(engine.get_open_positions()) == 0
