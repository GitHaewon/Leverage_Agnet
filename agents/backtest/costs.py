"""
백테스트 비용 계산기 — Fee / Slippage / Funding Fee.

Binance Futures 기준:
  - Taker 수수료: 0.04% (시장가)
  - Maker 수수료: 0.02% (지정가)
  - 펀딩비: 8시간마다 (00:00 / 08:00 / 16:00 UTC)
  - 슬리피지: 고정 비율 또는 거래량 기반
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from agents.backtest.models import BacktestConfig, OHLCVBar, Trade


# ════════════════════════════════════════════════════════════════
# 수수료 계산기
# ════════════════════════════════════════════════════════════════

class FeeCalculator:
    """
    Binance Futures 수수료 계산.

    시장가 주문 기준 taker fee 사용.
    position_value = quantity × price × leverage (레버리지 고려 없음 — 증거금 기준)

    Binance 실제 수수료:
      - 수수료 = 명목 포지션 가치 × fee_rate
      - 명목 가치 = quantity × price (레버리지 무관)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._fee_rate = Decimal(str(
            config.taker_fee_rate if config.use_taker_fee else config.maker_fee_rate
        ))

    @property
    def fee_rate(self) -> Decimal:
        return self._fee_rate

    def calculate(
        self,
        quantity: Decimal,
        price: Decimal,
    ) -> Decimal:
        """
        수수료 = 명목 포지션 가치 × fee_rate

        Args:
            quantity: 코인 수량
            price: 체결 가격

        Returns:
            수수료 금액 (USDT)
        """
        notional = quantity * price
        return (notional * self._fee_rate).quantize(Decimal("0.00000001"))

    def round_trip_fee(
        self,
        quantity: Decimal,
        entry_price: Decimal,
        exit_price: Decimal,
    ) -> Decimal:
        """진입 + 청산 왕복 수수료."""
        entry_fee = self.calculate(quantity, entry_price)
        exit_fee  = self.calculate(quantity, exit_price)
        return entry_fee + exit_fee


# ════════════════════════════════════════════════════════════════
# 슬리피지 모델
# ════════════════════════════════════════════════════════════════

class SlippageModel:
    """
    슬리피지 시뮬레이션.

    Fixed 모델: 체결가 = 시그널가 × (1 ± slippage_rate)
    Volume 모델: 대량 주문일수록 더 큰 슬리피지

    방향:
      LONG 진입/SHORT 청산 (매수): 가격 × (1 + slippage) → 더 비싸게 체결
      SHORT 진입/LONG 청산 (매도): 가격 × (1 - slippage) → 더 싸게 체결
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._model = config.slippage_model
        self._rate = Decimal(str(config.slippage_rate))
        self._volume_factor = config.slippage_volume_factor

    def apply_entry(
        self,
        direction: str,
        signal_price: Decimal,
        quantity: Decimal,
        bar_volume: Decimal | None = None,
    ) -> tuple[Decimal, Decimal]:
        """
        진입 슬리피지 적용.

        Returns:
            (actual_price, slippage_cost_usdt)
        """
        rate = self._compute_rate(quantity, bar_volume)
        if direction == "LONG":
            actual = signal_price * (Decimal("1") + rate)
        else:  # SHORT
            actual = signal_price * (Decimal("1") - rate)
        cost = abs(actual - signal_price) * quantity
        return actual, cost

    def apply_exit(
        self,
        direction: str,
        signal_price: Decimal,
        quantity: Decimal,
        bar_volume: Decimal | None = None,
    ) -> tuple[Decimal, Decimal]:
        """
        청산 슬리피지 적용.
        LONG 청산(매도): 더 싸게 팔림 → 불리
        SHORT 청산(매수): 더 비싸게 삼 → 불리
        """
        rate = self._compute_rate(quantity, bar_volume)
        if direction == "LONG":
            actual = signal_price * (Decimal("1") - rate)
        else:  # SHORT
            actual = signal_price * (Decimal("1") + rate)
        cost = abs(actual - signal_price) * quantity
        return actual, cost

    def _compute_rate(
        self,
        quantity: Decimal,
        bar_volume: Decimal | None,
    ) -> Decimal:
        if self._model == "fixed":
            return self._rate

        # Volume 모델: 주문량 / 봉 거래량 비율에 비례
        if bar_volume is None or bar_volume == 0:
            return self._rate
        volume_ratio = float(quantity / bar_volume)
        rate = self._rate * Decimal(str(1 + volume_ratio * self._volume_factor))
        # 최대 슬리피지 1% 상한
        return min(rate, Decimal("0.01"))


# ════════════════════════════════════════════════════════════════
# 펀딩비 누적기
# ════════════════════════════════════════════════════════════════

class FundingFeeAccumulator:
    """
    Binance Futures 펀딩비 누적 계산.

    규칙:
      - 8시간마다 (00:00, 08:00, 16:00 UTC) 부과
      - funding_fee = notional_value × funding_rate
      - notional_value = quantity × mark_price (레버리지 무관)
      - LONG: funding_rate > 0 → 지불 (비용), < 0 → 수취 (수익)
      - SHORT: 반대
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._interval_hours = config.funding_interval_hours
        self._default_rate = config.default_funding_rate
        self._apply = config.apply_funding_fee

    def get_funding_timestamps(
        self,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        """start ~ end 기간 내 모든 펀딩비 부과 시점 반환."""
        times: list[datetime] = []
        if not self._apply:
            return times

        # UTC 기준 00:00, 08:00, 16:00
        current = start.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        while current <= end:
            hour = current.hour
            if hour % self._interval_hours == 0:
                if start < current <= end:
                    times.append(current)
            current += timedelta(hours=1)
        return times

    def calculate_single(
        self,
        direction: str,
        quantity: Decimal,
        mark_price: Decimal,
        funding_rate: float | None = None,
    ) -> Decimal:
        """
        단일 펀딩비 부과 계산.

        LONG: 양수 funding_rate → 지불(비용으로 차감)
        SHORT: 양수 funding_rate → 수취(수익으로 가산)
        반환값: 양수 = 비용, 음수 = 수익
        """
        if not self._apply:
            return Decimal("0")

        rate = Decimal(str(funding_rate if funding_rate is not None else self._default_rate))
        notional = quantity * mark_price
        fee_amount = notional * rate

        # LONG은 지불, SHORT는 수취 (방향 반전)
        if direction == "LONG":
            return fee_amount   # 양수 = 비용
        else:
            return -fee_amount  # 음수 = 수익 (비용 절감)

    def accumulate_for_trade(
        self,
        trade: Trade,
        bars: list[OHLCVBar],
    ) -> Decimal:
        """
        포지션 보유 기간 전체의 펀딩비 합산.

        Args:
            trade:  오픈 상태의 거래
            bars:   entry_time ~ exit_time 기간의 OHLCV 봉

        Returns:
            총 펀딩비 (양수 = 비용, 음수 = 수익)
        """
        if not self._apply:
            return Decimal("0")

        total = Decimal("0")
        exit_time = trade.exit_time or bars[-1].timestamp if bars else trade.entry_time

        for bar in bars:
            if not bar.is_funding_bar:
                continue
            if not (trade.entry_time < bar.timestamp <= exit_time):
                continue

            fee = self.calculate_single(
                direction=trade.direction,
                quantity=trade.quantity,
                mark_price=bar.close,
                funding_rate=bar.funding_rate,
            )
            total += fee

        return total


# ════════════════════════════════════════════════════════════════
# 비용 요약 계산기
# ════════════════════════════════════════════════════════════════

def mark_funding_bars(bars: list[OHLCVBar]) -> list[OHLCVBar]:
    """8h 간격 펀딩비 부과 봉 표시."""
    for bar in bars:
        hour = bar.timestamp.hour
        bar.is_funding_bar = (hour % 8 == 0)
    return bars


def net_pnl_from_prices(
    direction: str,
    quantity: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    leverage: int,
) -> Decimal:
    """
    레버리지 포함 총 PnL (수수료/슬리피지 제외).

    LONG: (exit - entry) × quantity × leverage
    SHORT: (entry - exit) × quantity × leverage

    주의: 여기서 leverage는 이미 quantity에 반영되어 있으면 1로 설정.
    Binance Futures에서는 quantity = 코인 수량 (leverage 무관),
    PnL = (exit - entry) × quantity (LONG)
    """
    if direction == "LONG":
        return (exit_price - entry_price) * quantity
    else:
        return (entry_price - exit_price) * quantity
