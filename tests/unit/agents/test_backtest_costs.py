"""
백테스트 비용 계산기 단위 테스트 — Fee / Slippage / FundingFee.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.backtest.costs import (
    FeeCalculator,
    FundingFeeAccumulator,
    SlippageModel,
    mark_funding_bars,
    net_pnl_from_prices,
)
from agents.backtest.models import BacktestConfig, OHLCVBar


def _config(**kwargs) -> BacktestConfig:
    return BacktestConfig(**kwargs)


def _bar(
    ts: str,
    open: str = "67450",
    high: str = "67600",
    low: str = "67300",
    close: str = "67500",
    volume: str = "100",
    funding_rate: float = 0.0001,
) -> OHLCVBar:
    return OHLCVBar(
        timestamp=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        funding_rate=funding_rate,
    )


# ════════════════════════════════════════════════════════════════
# Fee Calculator
# ════════════════════════════════════════════════════════════════

class TestFeeCalculator:
    def test_taker_fee_04_pct(self) -> None:
        config = _config(taker_fee_rate=0.0004, use_taker_fee=True)
        calc = FeeCalculator(config)

        # 0.01 BTC × $67,450 = $674.50 × 0.04% = $0.2698
        fee = calc.calculate(Decimal("0.01"), Decimal("67450"))
        assert fee == pytest.approx(Decimal("0.2698"), rel=Decimal("0.001"))

    def test_maker_fee_02_pct(self) -> None:
        config = _config(maker_fee_rate=0.0002, use_taker_fee=False)
        calc = FeeCalculator(config)

        fee = calc.calculate(Decimal("0.01"), Decimal("67450"))
        assert fee == pytest.approx(Decimal("0.1349"), rel=Decimal("0.001"))

    def test_round_trip_fee_is_double(self) -> None:
        config = _config(taker_fee_rate=0.0004, use_taker_fee=True)
        calc = FeeCalculator(config)

        single = calc.calculate(Decimal("0.01"), Decimal("67450"))
        roundtrip = calc.round_trip_fee(
            Decimal("0.01"), Decimal("67450"), Decimal("68000")
        )
        # 진입 + 청산 (약간 다른 가격)
        assert roundtrip > single

    def test_zero_quantity_zero_fee(self) -> None:
        config = _config()
        calc = FeeCalculator(config)
        assert calc.calculate(Decimal("0"), Decimal("67450")) == Decimal("0")


# ════════════════════════════════════════════════════════════════
# Slippage Model
# ════════════════════════════════════════════════════════════════

class TestSlippageModel:
    def test_long_entry_price_increases(self) -> None:
        """LONG 진입: 슬리피지로 가격 상승 (더 비싸게 매수)."""
        config = _config(slippage_model="fixed", slippage_rate=0.0005)
        model = SlippageModel(config)

        actual, cost = model.apply_entry("LONG", Decimal("67450"), Decimal("0.01"))
        assert actual > Decimal("67450")
        assert actual == pytest.approx(Decimal("67450") * Decimal("1.0005"), rel=Decimal("0.0001"))

    def test_short_entry_price_decreases(self) -> None:
        """SHORT 진입: 슬리피지로 가격 하락 (더 싸게 매도)."""
        config = _config(slippage_model="fixed", slippage_rate=0.0005)
        model = SlippageModel(config)

        actual, _ = model.apply_entry("SHORT", Decimal("67450"), Decimal("0.01"))
        assert actual < Decimal("67450")

    def test_long_exit_price_decreases(self) -> None:
        """LONG 청산 (매도): 슬리피지로 가격 하락 (더 싸게 팔림)."""
        config = _config(slippage_model="fixed", slippage_rate=0.0005)
        model = SlippageModel(config)

        actual, _ = model.apply_exit("LONG", Decimal("69200"), Decimal("0.01"))
        assert actual < Decimal("69200")

    def test_short_exit_price_increases(self) -> None:
        """SHORT 청산 (매수): 슬리피지로 가격 상승."""
        config = _config(slippage_model="fixed", slippage_rate=0.0005)
        model = SlippageModel(config)

        actual, _ = model.apply_exit("SHORT", Decimal("65000"), Decimal("0.01"))
        assert actual > Decimal("65000")

    def test_slippage_cost_is_positive(self) -> None:
        config = _config(slippage_model="fixed", slippage_rate=0.001)
        model = SlippageModel(config)

        _, cost = model.apply_entry("LONG", Decimal("67450"), Decimal("0.01"))
        assert cost > 0

    def test_volume_model_caps_at_1_pct(self) -> None:
        """볼륨 모델: 최대 1% 슬리피지 상한."""
        config = _config(slippage_model="volume", slippage_rate=0.0005, slippage_volume_factor=100)
        model = SlippageModel(config)

        # 아주 큰 주문 vs 작은 거래량 → 최대 1% 상한
        actual, _ = model.apply_entry("LONG", Decimal("67450"), Decimal("1000"), Decimal("10"))
        max_price = Decimal("67450") * Decimal("1.01")
        assert actual <= max_price * Decimal("1.001")  # 허용 오차 포함

    def test_zero_slippage_rate(self) -> None:
        config = _config(slippage_rate=0.0)
        model = SlippageModel(config)

        actual, cost = model.apply_entry("LONG", Decimal("67450"), Decimal("0.01"))
        assert actual == Decimal("67450")
        assert cost == Decimal("0")


# ════════════════════════════════════════════════════════════════
# Funding Fee Accumulator
# ════════════════════════════════════════════════════════════════

class TestFundingFeeAccumulator:
    def test_long_pays_positive_funding(self) -> None:
        """LONG 포지션: 양수 펀딩비 = 비용."""
        config = _config(default_funding_rate=0.0001, apply_funding_fee=True)
        acc = FundingFeeAccumulator(config)

        fee = acc.calculate_single("LONG", Decimal("0.01"), Decimal("67450"), 0.0001)
        # notional = 0.01 × 67450 = 674.5, fee = 674.5 × 0.0001 = 0.06745
        assert fee == pytest.approx(Decimal("0.06745"), rel=Decimal("0.001"))
        assert fee > 0   # 양수 = LONG 비용

    def test_short_receives_positive_funding(self) -> None:
        """SHORT 포지션: 양수 펀딩비 = 수익 (음수 반환)."""
        config = _config(default_funding_rate=0.0001, apply_funding_fee=True)
        acc = FundingFeeAccumulator(config)

        fee = acc.calculate_single("SHORT", Decimal("0.01"), Decimal("67450"), 0.0001)
        assert fee < 0   # 음수 = 수익

    def test_negative_funding_rate_reverses(self) -> None:
        """음수 펀딩비: LONG이 수취, SHORT가 지불."""
        config = _config(apply_funding_fee=True)
        acc = FundingFeeAccumulator(config)

        long_fee  = acc.calculate_single("LONG",  Decimal("0.01"), Decimal("67450"), -0.0001)
        short_fee = acc.calculate_single("SHORT", Decimal("0.01"), Decimal("67450"), -0.0001)

        assert long_fee  < 0   # LONG 수취
        assert short_fee > 0   # SHORT 지불

    def test_disabled_funding_returns_zero(self) -> None:
        config = _config(apply_funding_fee=False)
        acc = FundingFeeAccumulator(config)

        fee = acc.calculate_single("LONG", Decimal("0.01"), Decimal("67450"), 0.0001)
        assert fee == Decimal("0")

    def test_funding_timestamps_every_8h(self) -> None:
        config = _config(apply_funding_fee=True)
        acc = FundingFeeAccumulator(config)

        start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)

        times = acc.get_funding_timestamps(start, end)
        # 하루 = 3번 (08:00, 16:00, 24:00)
        assert len(times) == 3


# ════════════════════════════════════════════════════════════════
# mark_funding_bars
# ════════════════════════════════════════════════════════════════

class TestMarkFundingBars:
    def test_marks_correct_hours(self) -> None:
        bars = [
            _bar("2026-06-01 00:00"),   # 펀딩 봉
            _bar("2026-06-01 01:00"),   # 일반 봉
            _bar("2026-06-01 08:00"),   # 펀딩 봉
            _bar("2026-06-01 16:00"),   # 펀딩 봉
        ]
        marked = mark_funding_bars(bars)
        assert marked[0].is_funding_bar is True
        assert marked[1].is_funding_bar is False
        assert marked[2].is_funding_bar is True
        assert marked[3].is_funding_bar is True


# ════════════════════════════════════════════════════════════════
# net_pnl_from_prices
# ════════════════════════════════════════════════════════════════

class TestNetPnlFromPrices:
    def test_long_profit(self) -> None:
        pnl = net_pnl_from_prices(
            "LONG", Decimal("0.01"), Decimal("67450"), Decimal("69200"), 1
        )
        # 0.01 × (69200 - 67450) = 0.01 × 1750 = 17.50
        assert pnl == Decimal("17.50")

    def test_long_loss(self) -> None:
        pnl = net_pnl_from_prices(
            "LONG", Decimal("0.01"), Decimal("67450"), Decimal("66800"), 1
        )
        # 0.01 × (66800 - 67450) = 0.01 × -650 = -6.50
        assert pnl == Decimal("-6.50")

    def test_short_profit(self) -> None:
        pnl = net_pnl_from_prices(
            "SHORT", Decimal("0.01"), Decimal("67450"), Decimal("65000"), 1
        )
        # 0.01 × (67450 - 65000) = 0.01 × 2450 = 24.50
        assert pnl == Decimal("24.50")

    def test_short_loss(self) -> None:
        pnl = net_pnl_from_prices(
            "SHORT", Decimal("0.01"), Decimal("67450"), Decimal("69000"), 1
        )
        # 0.01 × (67450 - 69000) = 0.01 × -1550 = -15.50
        assert pnl == Decimal("-15.50")
