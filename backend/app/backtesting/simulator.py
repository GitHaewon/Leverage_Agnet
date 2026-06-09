"""
Walk Forward Testing Engine — 거래 시뮬레이터.

TRADING_RULES.md 안전 규칙을 모든 시뮬레이션에 적용한다:
  §7.1  포지션 사이징: size = risk_amount / sl_distance
  §7.4  R:R 최소 2.0
  §11.3 신뢰도 최소 0.60
  §1.1  레버리지 상한: min(signal, user_max, SYSTEM_MAX=20)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .types import (
    MIN_CONFIDENCE,
    MIN_RR_RATIO,
    SYSTEM_MAX_LEVERAGE,
    SignalData,
    Trade,
    WalkForwardConfig,
)


def _compute_rr_ratio(signal: SignalData) -> float:
    """
    LONG: (tp - entry) / (entry - sl)
    SHORT: (entry - tp) / (sl - entry)
    """
    if signal.direction == "LONG":
        profit_dist = signal.take_profit - signal.entry_price
        loss_dist = signal.entry_price - signal.stop_loss
    else:
        profit_dist = signal.entry_price - signal.take_profit
        loss_dist = signal.stop_loss - signal.entry_price

    if loss_dist <= 0:
        return 0.0
    return profit_dist / loss_dist


def _validate_signal(signal: SignalData, config: WalkForwardConfig) -> bool:
    """TRADING_RULES.md §7.4, §11.3 진입 전 검증."""
    if signal.confidence < MIN_CONFIDENCE:
        return False
    if _compute_rr_ratio(signal) < MIN_RR_RATIO:
        return False
    return True


def _calc_position(
    signal: SignalData,
    config: WalkForwardConfig,
    balance: float,
) -> tuple[float, float, int]:
    """
    TRADING_RULES.md §7.1 포지션 사이징.

    sl_distance   = |entry_price - stop_loss_price|
    risk_amount   = account_balance × risk_per_trade
    position_size = risk_amount / sl_distance  (증거금)
    quantity      = (position_size × leverage) / entry_price

    반환: (quantity, margin_used, final_leverage)
    """
    final_lev = min(signal.leverage, config.max_leverage, SYSTEM_MAX_LEVERAGE)
    sl_distance = abs(signal.entry_price - signal.stop_loss)
    if sl_distance <= 0:
        return 0.0, 0.0, final_lev

    risk_amount = balance * config.risk_per_trade
    margin_used = risk_amount / sl_distance
    quantity = (margin_used * final_lev) / signal.entry_price
    return quantity, margin_used, final_lev


class TradeSimulator:
    """
    OHLCV 봉 단위 시뮬레이터.

    시그널 timestamp 다음 봉의 open에서 진입하고,
    이후 봉에서 TP/SL 도달 여부를 스캔한다.
    """

    def run(
        self,
        ohlcv: pd.DataFrame,
        signals: list[SignalData],
        config: WalkForwardConfig,
        initial_capital: float,
    ) -> tuple[list[Trade], list[float]]:
        """
        반환: (trade_list, equity_curve)
        equity_curve[0] = initial_capital
        equity_curve[i] = i번째 거래 후 잔고
        """
        balance = initial_capital
        trades: list[Trade] = []
        equity_curve: list[float] = [balance]

        for signal in signals:
            if not _validate_signal(signal, config):
                continue

            entry_idx = self._find_entry_bar(ohlcv, signal.timestamp)
            if entry_idx is None:
                continue

            quantity, margin_used, lev = _calc_position(signal, config, balance)
            if quantity <= 0:
                continue

            trade = self._simulate_trade(
                ohlcv=ohlcv,
                signal=signal,
                entry_bar=entry_idx,
                quantity=quantity,
                margin_used=margin_used,
                leverage=lev,
                config=config,
            )
            if trade is None:
                continue

            balance += trade.pnl_usdt
            trades.append(trade)
            equity_curve.append(balance)

        return trades, equity_curve

    def _find_entry_bar(self, ohlcv: pd.DataFrame, ts: datetime) -> int | None:
        """
        시그널 timestamp 이후 첫 번째 봉 인덱스.
        진입은 다음 봉 open에서 실행된다고 가정한다.
        """
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        idx = ohlcv.index.searchsorted(ts, side="right")
        if idx >= len(ohlcv):
            return None
        return int(idx)

    def _simulate_trade(
        self,
        ohlcv: pd.DataFrame,
        signal: SignalData,
        entry_bar: int,
        quantity: float,
        margin_used: float,
        leverage: int,
        config: WalkForwardConfig,
    ) -> Trade | None:
        """
        entry_bar의 open으로 진입 후 이후 봉에서 TP/SL 스캔.
        윈도우 끝까지 미결이면 마지막 close로 청산.
        """
        raw_entry = float(ohlcv["open"].iloc[entry_bar])
        entry_time = ohlcv.index[entry_bar]
        if hasattr(entry_time, "to_pydatetime"):
            entry_time = entry_time.to_pydatetime()

        # 슬리피지: LONG은 불리하게 높게, SHORT은 낮게
        slippage = raw_entry * config.slippage_rate
        if signal.direction == "LONG":
            effective_entry = raw_entry + slippage
        else:
            effective_entry = raw_entry - slippage

        rr = _compute_rr_ratio(signal)
        close_reason = "window_end"
        exit_price = float(ohlcv["close"].iloc[-1])
        exit_time = ohlcv.index[-1]

        for bar in range(entry_bar + 1, len(ohlcv)):
            high = float(ohlcv["high"].iloc[bar])
            low = float(ohlcv["low"].iloc[bar])

            if signal.direction == "LONG":
                # 같은 봉에서 양쪽 모두 도달 시 보수적으로 SL 우선
                if low <= signal.stop_loss:
                    close_reason = "sl_hit"
                    exit_price = signal.stop_loss
                    exit_time = ohlcv.index[bar]
                    break
                if high >= signal.take_profit:
                    close_reason = "tp_hit"
                    exit_price = signal.take_profit
                    exit_time = ohlcv.index[bar]
                    break
            else:  # SHORT
                if high >= signal.stop_loss:
                    close_reason = "sl_hit"
                    exit_price = signal.stop_loss
                    exit_time = ohlcv.index[bar]
                    break
                if low <= signal.take_profit:
                    close_reason = "tp_hit"
                    exit_price = signal.take_profit
                    exit_time = ohlcv.index[bar]
                    break

        if hasattr(exit_time, "to_pydatetime"):
            exit_time = exit_time.to_pydatetime()

        if signal.direction == "LONG":
            gross_pnl = (exit_price - effective_entry) * quantity
        else:
            gross_pnl = (effective_entry - exit_price) * quantity

        commission = (
            effective_entry * quantity + exit_price * quantity
        ) * config.commission_rate

        pnl_usdt = gross_pnl - commission
        pnl_pct = pnl_usdt / margin_used if margin_used > 0 else 0.0

        return Trade(
            entry_time=entry_time,
            exit_time=exit_time,
            direction=signal.direction,
            entry_price=effective_entry,
            exit_price=exit_price,
            quantity=quantity,
            leverage=leverage,
            margin_used=margin_used,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            rr_ratio=rr,
            close_reason=close_reason,
            gross_pnl=gross_pnl,
            commission=commission,
        )
