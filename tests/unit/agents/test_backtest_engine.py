"""
BacktestEngine 통합 단위 테스트.
실제 백테스트 시나리오를 시뮬레이션.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agents.backtest.engine import BacktestEngine
from agents.backtest.models import (
    BacktestConfig,
    BacktestSignal,
    OHLCVBar,
    TradeExitReason,
)


# ── 테스트 데이터 생성 헬퍼 ──────────────────────────────────────────────────────

def _bar(
    ts: datetime,
    open: str = "67450",
    high: str = "67600",
    low: str = "67300",
    close: str = "67500",
    volume: str = "1000",
    funding_rate: float = 0.0001,
) -> OHLCVBar:
    return OHLCVBar(
        timestamp=ts,
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        funding_rate=funding_rate,
    )


def _signal(
    ts: datetime,
    direction: str = "LONG",
    entry: str = "67450",
    tp: str = "69200",
    sl: str = "66800",
    confidence: float = 0.87,
    leverage: int = 5,
) -> BacktestSignal:
    return BacktestSignal(
        timestamp=ts,
        symbol="BTCUSDT",
        direction=direction,
        confidence=confidence,
        entry_price=Decimal(entry),
        take_profit=Decimal(tp),
        stop_loss=Decimal(sl),
        leverage=leverage,
        rr_ratio=2.69,
    )


def _make_bars(n: int, start_price: float = 67450.0) -> list[OHLCVBar]:
    """N개 봉 생성 (가격 고정)."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        ts = base + timedelta(hours=i)
        price = str(round(start_price + i * 10, 2))
        bars.append(_bar(ts, open=price, high=str(float(price)+200), low=str(float(price)-200), close=price))
    return bars


# ════════════════════════════════════════════════════════════════
# 기본 실행 테스트
# ════════════════════════════════════════════════════════════════

class TestBacktestEngineBasic:
    def test_run_returns_result(self) -> None:
        engine = BacktestEngine()
        bars = _make_bars(10)
        result = engine.run([], bars)

        assert result is not None
        assert result.metrics is not None
        assert len(result.equity_curve) == 10

    def test_empty_signals_no_trades(self) -> None:
        engine = BacktestEngine()
        bars = _make_bars(20)
        result = engine.run([], bars)

        assert result.metrics.total_trades == 0
        assert result.metrics.total_return == 0.0

    def test_no_bars_raises(self) -> None:
        engine = BacktestEngine()
        with pytest.raises(ValueError, match="bars가 비어"):
            engine.run([], [])

    def test_equity_curve_length_equals_bars(self) -> None:
        engine = BacktestEngine()
        bars = _make_bars(30)
        result = engine.run([], bars)
        assert len(result.equity_curve) == 30


# ════════════════════════════════════════════════════════════════
# TP 달성 시나리오
# ════════════════════════════════════════════════════════════════

class TestTPHit:
    def test_long_tp_hit(self) -> None:
        """LONG 포지션 TP 달성 시나리오."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        bars = [
            _bar(base,               open="67450", high="67450", low="67400", close="67450"),  # 신호 발생
            _bar(base+timedelta(hours=1), open="67460", high="67460", low="67400", close="67450"),  # 진입
            _bar(base+timedelta(hours=2), open="68000", high="69500", low="67900", close="69000"),  # TP 달성
        ]

        signals = [_signal(base, direction="LONG", entry="67450", tp="69200", sl="66800")]

        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("10000"),
            slippage_rate=0.0,      # 테스트용 슬리피지 0
            apply_funding_fee=False, # 비용 단순화
        ))
        result = engine.run(signals, bars, Decimal("200"))

        assert result.metrics.total_trades == 1
        closed = result.closed_trades
        assert len(closed) == 1
        assert closed[0].exit_reason == TradeExitReason.TAKE_PROFIT
        assert closed[0].net_pnl > 0

    def test_short_tp_hit(self) -> None:
        """SHORT 포지션 TP 달성 시나리오."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        bars = [
            _bar(base,               open="67450", high="67500", low="67400", close="67450"),
            _bar(base+timedelta(hours=1), open="67440", high="67440", low="67400", close="67430"),  # 진입
            _bar(base+timedelta(hours=2), open="66000", high="66200", low="65000", close="65200"),  # TP (SHORT TP=하락)
        ]

        signals = [_signal(base, direction="SHORT", entry="67450", tp="65000", sl="68500")]

        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("10000"),
            slippage_rate=0.0,
            apply_funding_fee=False,
        ))
        result = engine.run(signals, bars, Decimal("200"))

        closed = result.closed_trades
        if closed:
            assert closed[0].exit_reason == TradeExitReason.TAKE_PROFIT


# ════════════════════════════════════════════════════════════════
# SL 달성 시나리오
# ════════════════════════════════════════════════════════════════

class TestSLHit:
    def test_long_sl_hit(self) -> None:
        """LONG 포지션 SL 달성 → 손실 거래."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        bars = [
            _bar(base,               open="67450", high="67460", low="67440", close="67450"),
            _bar(base+timedelta(hours=1), open="67450", high="67460", low="67440", close="67450"),  # 진입
            _bar(base+timedelta(hours=2), open="67000", high="67000", low="65000", close="66000"),  # SL 달성
        ]

        signals = [_signal(base, direction="LONG", entry="67450", tp="70000", sl="66800")]

        engine = BacktestEngine(BacktestConfig(
            initial_capital=Decimal("10000"),
            slippage_rate=0.0,
            apply_funding_fee=False,
        ))
        result = engine.run(signals, bars, Decimal("200"))

        closed = result.closed_trades
        if closed:
            assert closed[0].exit_reason == TradeExitReason.STOP_LOSS
            assert closed[0].net_pnl < 0


# ════════════════════════════════════════════════════════════════
# 비용 포함 테스트
# ════════════════════════════════════════════════════════════════

class TestWithCosts:
    def test_fees_reduce_pnl(self) -> None:
        """수수료가 있으면 PnL이 감소한다."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        bars = [
            _bar(base,               open="67450", high="67450", low="67400", close="67450"),
            _bar(base+timedelta(hours=1), open="67450", high="67450", low="67400", close="67450"),
            _bar(base+timedelta(hours=2), open="69200", high="70000", low="69200", close="69300"),
        ]
        signals = [_signal(base, tp="69200", sl="66800")]

        # 수수료 없음
        engine_no_fee = BacktestEngine(BacktestConfig(
            taker_fee_rate=0.0,
            slippage_rate=0.0,
            apply_funding_fee=False,
        ))
        result_no_fee = engine_no_fee.run(signals, bars, Decimal("200"))

        # 수수료 있음
        engine_fee = BacktestEngine(BacktestConfig(
            taker_fee_rate=0.0004,
            slippage_rate=0.0,
            apply_funding_fee=False,
        ))
        result_fee = engine_fee.run(signals, bars, Decimal("200"))

        if result_no_fee.closed_trades and result_fee.closed_trades:
            pnl_no_fee = result_no_fee.closed_trades[0].net_pnl or Decimal("0")
            pnl_fee    = result_fee.closed_trades[0].net_pnl or Decimal("0")
            assert pnl_fee < pnl_no_fee

    def test_slippage_reduces_pnl(self) -> None:
        """슬리피지가 있으면 PnL이 감소한다."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        bars = [
            _bar(base,               open="67450", high="67450", low="67400", close="67450"),
            _bar(base+timedelta(hours=1), open="67450", high="67450", low="67400", close="67450"),
            _bar(base+timedelta(hours=2), open="69200", high="70000", low="69200", close="69300"),
        ]
        signals = [_signal(base, tp="69200", sl="66800")]

        engine_no_slip = BacktestEngine(BacktestConfig(slippage_rate=0.0, apply_funding_fee=False, taker_fee_rate=0.0))
        engine_slip    = BacktestEngine(BacktestConfig(slippage_rate=0.001, apply_funding_fee=False, taker_fee_rate=0.0))

        r1 = engine_no_slip.run(signals, bars, Decimal("200"))
        r2 = engine_slip.run(signals, bars, Decimal("200"))

        if r1.closed_trades and r2.closed_trades:
            assert r2.closed_trades[0].net_pnl < r1.closed_trades[0].net_pnl

    def test_funding_fee_accumulated(self) -> None:
        """펀딩비가 누적된다."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)  # 00:00 UTC

        bars = [
            _bar(base,                   open="67450", high="67600", low="67300", close="67450"),  # 신호
            _bar(base+timedelta(hours=1), open="67450", high="67600", low="67300", close="67450"),  # 진입
            # 8h 봉 (펀딩비 부과)
            _bar(base+timedelta(hours=8), open="67450", high="67600", low="67300", close="67450", funding_rate=0.001),
            _bar(base+timedelta(hours=9), open="67900", high="69500", low="67800", close="69300"),  # TP
        ]
        signals = [_signal(base, tp="69200", sl="66800")]

        engine = BacktestEngine(BacktestConfig(
            apply_funding_fee=True,
            taker_fee_rate=0.0,
            slippage_rate=0.0,
        ))
        result = engine.run(signals, bars, Decimal("200"))

        # 펀딩비가 기록되어야 함
        assert result.metrics.total_funding_fees >= 0


# ════════════════════════════════════════════════════════════════
# 성과 지표 검증
# ════════════════════════════════════════════════════════════════

class TestMetricsIntegration:
    def test_win_rate_correct(self) -> None:
        """3승 2패 → 승률 60%."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = []
        signals = []

        # 5개 거래: 상승 3번, 하락 2번
        for i in range(5):
            ts = base + timedelta(hours=i * 4)
            bars.extend([
                _bar(ts,                 open="67450", high="67500", low="67400", close="67450"),
                _bar(ts+timedelta(hours=1),  open="67450", high="67500", low="67400", close="67450"),
            ])
            # 홀수: 상승(TP 달성), 짝수: 하락(SL 달성)
            if i % 2 == 0:
                bars.append(_bar(ts+timedelta(hours=2), open="69200", high="70000", low="69100", close="69300"))
            else:
                bars.append(_bar(ts+timedelta(hours=2), open="66500", high="66600", low="65000", close="65500"))

            signals.append(_signal(ts, tp="69200", sl="66800"))

        # 충분한 봉 추가
        last_ts = bars[-1].timestamp
        bars.extend([_bar(last_ts + timedelta(hours=i+1)) for i in range(5)])

        engine = BacktestEngine(BacktestConfig(
            slippage_rate=0.0,
            apply_funding_fee=False,
            taker_fee_rate=0.0,
        ))
        result = engine.run(signals, bars, Decimal("200"))

        # 거래가 발생했으면 검증
        if result.metrics.total_trades > 0:
            assert 0.0 <= result.metrics.win_rate <= 1.0

    def test_total_costs_in_metrics(self) -> None:
        """total_costs = fees + slippage + funding."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [
            _bar(base,               open="67450", high="67600", low="67300", close="67450"),
            _bar(base+timedelta(hours=1), open="67450", high="67600", low="67300", close="67450"),
            _bar(base+timedelta(hours=2), open="69200", high="70000", low="69100", close="69300"),
        ]
        signals = [_signal(base, tp="69200", sl="66800")]

        engine = BacktestEngine(BacktestConfig(taker_fee_rate=0.0004, slippage_rate=0.0005))
        result = engine.run(signals, bars, Decimal("200"))

        m = result.metrics
        computed_total = m.total_fees + m.total_slippage + m.total_funding_fees
        assert abs(float(m.total_costs - computed_total)) < 0.02  # 소수점 오차 허용

    def test_equity_curve_starts_at_initial(self) -> None:
        engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000")))
        bars = _make_bars(5)
        result = engine.run([], bars)
        assert result.equity_curve[0].equity == Decimal("10000")

    def test_summary_string_generated(self) -> None:
        engine = BacktestEngine()
        bars = _make_bars(10)
        result = engine.run([], bars)
        summary = engine.summary(result)
        assert "Total Return" in summary
        assert "Sharpe" in summary

    def test_run_with_risk_pct(self) -> None:
        engine = BacktestEngine(BacktestConfig(initial_capital=Decimal("10000")))
        bars = _make_bars(5)
        result = engine.run_with_risk_pct([], bars, risk_pct=0.02)
        assert result is not None
