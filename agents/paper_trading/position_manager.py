"""
PositionManager — Paper 포지션 생명주기 관리.

  open_position()    → LONG/SHORT 포지션 생성
  update_price()     → 현재가 갱신 + TP/SL 도달 여부 반환
  close_position()   → 전량 청산 + PaperTradeRecord 생성
  partial_close()    → 부분 청산 (ratio: 0.0 ~ 1.0)
  apply_dca()        → 동일 방향 추가 진입 (평균 진입가 재계산)

수수료 모델:
  entry_fee = quantity × entry_price × taker_fee_rate
  exit_fee  = close_qty × close_price × taker_fee_rate
  총 fee    = entry_fee + exit_fee
  net_pnl   = gross_pnl - exit_fee  (entry_fee는 포지션 오픈 시 이미 차감)

잔고 모델:
  포지션 오픈: account._balance -= entry_fee  (margin은 locked으로 처리, 차감 안 함)
  포지션 청산: account._balance += net_pnl     (margin unlock → available로 복귀)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from agents.risk.models import RawSignal, ValidationResult
from agents.risk.sizing import recalculate_avg_entry
from agents.paper_trading.models import (
    PaperPosition,
    PaperTradeRecord,
    PaperUserSettings,
    TAKER_FEE_RATE,
    MAINTENANCE_MARGIN_RATE,
)
from agents.paper_trading.state import PaperAccountState


# 청산가 계산 상수 (Binance Isolated Margin 근사)
# LONG:  liq = entry × (1 - 1/leverage + maintenance_rate)
# SHORT: liq = entry × (1 + 1/leverage - maintenance_rate)


class PositionManager:
    """Paper 포지션 생명주기 관리자."""

    # ── 포지션 생성 ────────────────────────────────────────────────────────────

    def open_position(
        self,
        signal: RawSignal,
        validation: ValidationResult,
        account: PaperAccountState,
        settings: PaperUserSettings,
    ) -> PaperPosition:
        """
        Risk 검증이 통과된 시그널로 paper 포지션을 열고 계좌에 반영한다.
        """
        assert validation.approved, "open_position은 approved=True일 때만 호출 가능"
        assert signal.stop_loss is not None
        assert signal.take_profit is not None

        position_id = str(uuid.uuid4())
        qty = validation.quantity
        lev = validation.final_leverage
        margin = validation.margin_required_usdt
        entry_price = signal.entry_price

        # 진입 수수료 즉시 차감
        entry_fee = qty * entry_price * settings.taker_fee_rate
        account.debit_fee(entry_fee)

        liq_price = self._calc_liquidation_price(signal.direction, entry_price, lev)

        position = PaperPosition(
            id=position_id,
            user_id=settings.user_id,
            coin=signal.coin,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=entry_price,
            quantity=qty,
            original_quantity=qty,
            leverage=lev,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            liquidation_price=liq_price,
            margin_used=margin,
            original_margin=margin,
            max_loss_usdt=validation.max_loss_usdt,
            max_profit_usdt=validation.max_profit_usdt,
            original_risk_usdt=validation.max_loss_usdt,
            current_price=entry_price,
        )

        account.add_position(position)
        return position

    # ── 가격 업데이트 + TP/SL 체크 ────────────────────────────────────────────

    def update_price(
        self,
        position: PaperPosition,
        current_price: Decimal,
    ) -> Optional[str]:
        """
        현재가를 갱신하고 TP/SL 도달 여부를 반환한다.

        Returns:
            "tp_hit"  — Take Profit 도달
            "sl_hit"  — Stop Loss 도달
            None      — 포지션 유지
        """
        if not position.is_open:
            return None

        position.current_price = current_price

        if position.direction == "LONG":
            if current_price >= position.take_profit:
                return "tp_hit"
            if current_price <= position.stop_loss:
                return "sl_hit"
        else:  # SHORT
            if current_price <= position.take_profit:
                return "tp_hit"
            if current_price >= position.stop_loss:
                return "sl_hit"

        return None

    # ── 전량 청산 ──────────────────────────────────────────────────────────────

    def close_position(
        self,
        position: PaperPosition,
        close_price: Decimal,
        reason: str,
        account: PaperAccountState,
        settings: PaperUserSettings,
    ) -> PaperTradeRecord:
        """
        포지션을 전량 청산하고 TradeRecord를 생성한다.
        계좌 잔고에 net_pnl을 반영한다.
        """
        assert position.is_open, f"포지션 {position.id}는 이미 청산됨"

        now = datetime.now(timezone.utc)
        close_qty = position.quantity

        gross_pnl, exit_fee, net_pnl = self._calc_pnl(
            position.direction,
            position.entry_price,
            close_price,
            close_qty,
            settings.taker_fee_rate,
        )

        # entry_fee 비례분 계산 (전량 청산이므로 = original entry_fee)
        entry_fee_prop = position.original_quantity * position.entry_price * settings.taker_fee_rate
        close_ratio_used = close_qty / position.original_quantity
        entry_fee_portion = entry_fee_prop * close_ratio_used

        total_fee = entry_fee_portion + exit_fee
        pnl_pct = (net_pnl / position.margin_used * 100) if position.margin_used else Decimal("0")

        record = PaperTradeRecord(
            id=str(uuid.uuid4()),
            position_id=position.id,
            user_id=settings.user_id,
            coin=position.coin,
            direction=position.direction,
            entry_price=position.entry_price,
            close_price=close_price,
            quantity=close_qty,
            leverage=position.leverage,
            gross_pnl=gross_pnl.quantize(Decimal("0.01")),
            fee=total_fee.quantize(Decimal("0.0001")),
            net_pnl=net_pnl.quantize(Decimal("0.01")),
            pnl_pct=pnl_pct.quantize(Decimal("0.01")),
            duration_seconds=int((now - position.opened_at).total_seconds()),
            close_reason=reason,
            is_partial=False,
            opened_at=position.opened_at,
            closed_at=now,
        )

        # 잔고 반영: net_pnl (margin은 locked 해제 → available로 자동 복귀)
        account.credit_pnl(net_pnl)
        account.add_trade(record)

        # 포지션 상태 갱신
        position.status = "closed"
        position.closed_at = now
        position.close_reason = reason
        position.current_price = close_price
        position.realized_pnl += net_pnl
        account.remove_position(position.id)

        return record

    # ── 부분 청산 ──────────────────────────────────────────────────────────────

    def partial_close(
        self,
        position: PaperPosition,
        close_price: Decimal,
        ratio: float,
        account: PaperAccountState,
        settings: PaperUserSettings,
    ) -> Tuple[PaperPosition, PaperTradeRecord]:
        """
        포지션을 ratio 비율만큼 부분 청산한다.

        Args:
            ratio: 청산 비율 (0.0 초과 ~ 1.0 미만, 1.0이면 close_position 사용)

        Returns:
            (updated_position, trade_record)
        """
        assert position.is_open
        assert 0.0 < ratio < 1.0, f"partial_close ratio는 (0, 1) 범위여야 함: {ratio}"

        now = datetime.now(timezone.utc)
        close_qty = (position.quantity * Decimal(str(ratio))).quantize(
            position.quantity.normalize(),
            rounding=__import__("decimal").ROUND_DOWN,
        )

        if close_qty <= 0:
            raise ValueError(f"청산 수량이 0 이하: qty={position.quantity}, ratio={ratio}")

        gross_pnl, exit_fee, net_pnl = self._calc_pnl(
            position.direction,
            position.entry_price,
            close_price,
            close_qty,
            settings.taker_fee_rate,
        )

        entry_fee_portion = close_qty * position.entry_price * settings.taker_fee_rate
        total_fee = entry_fee_portion + exit_fee

        close_margin = position.margin_used * Decimal(str(ratio))
        pnl_pct = (net_pnl / close_margin * 100) if close_margin else Decimal("0")

        record = PaperTradeRecord(
            id=str(uuid.uuid4()),
            position_id=position.id,
            user_id=settings.user_id,
            coin=position.coin,
            direction=position.direction,
            entry_price=position.entry_price,
            close_price=close_price,
            quantity=close_qty,
            leverage=position.leverage,
            gross_pnl=gross_pnl.quantize(Decimal("0.01")),
            fee=total_fee.quantize(Decimal("0.0001")),
            net_pnl=net_pnl.quantize(Decimal("0.01")),
            pnl_pct=pnl_pct.quantize(Decimal("0.01")),
            duration_seconds=int((now - position.opened_at).total_seconds()),
            close_reason="partial",
            is_partial=True,
            opened_at=position.opened_at,
            closed_at=now,
        )

        # 잔고 반영
        account.credit_pnl(net_pnl)
        account.add_trade(record)

        # 포지션 업데이트
        position.quantity -= close_qty
        position.margin_used -= close_margin
        position.realized_pnl += net_pnl
        position.status = "partially_closed"
        position.current_price = close_price

        return position, record

    # ── DCA ────────────────────────────────────────────────────────────────────

    def apply_dca(
        self,
        position: PaperPosition,
        signal: RawSignal,
        validation: ValidationResult,
        account: PaperAccountState,
        settings: PaperUserSettings,
    ) -> PaperPosition:
        """
        기존 포지션에 DCA(동일 방향 추가 진입)를 적용한다.
        평균 진입가를 재계산하고 수량 + 증거금을 합산한다.
        """
        assert validation.approved
        assert position.direction == signal.direction, "DCA는 동일 방향만 가능"

        dca_qty = validation.quantity
        dca_entry = signal.entry_price
        dca_margin = validation.margin_required_usdt

        # 진입 수수료 차감
        entry_fee = dca_qty * dca_entry * settings.taker_fee_rate
        account.debit_fee(entry_fee)

        # 평균 진입가 재계산 (§8.3)
        new_avg_entry = recalculate_avg_entry(
            original_qty=position.quantity,
            original_entry=position.entry_price,
            dca_qty=dca_qty,
            dca_entry=dca_entry,
        )

        position.entry_price = new_avg_entry
        position.quantity += dca_qty
        position.original_quantity += dca_qty
        position.margin_used += dca_margin
        position.original_margin += dca_margin
        position.max_loss_usdt += validation.max_loss_usdt
        position.max_profit_usdt += validation.max_profit_usdt
        position.dca_count += 1

        # 청산가 재계산
        position.liquidation_price = self._calc_liquidation_price(
            position.direction, new_avg_entry, position.leverage
        )

        return position

    # ── 내부 계산 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_pnl(
        direction: str,
        entry_price: Decimal,
        close_price: Decimal,
        quantity: Decimal,
        fee_rate: Decimal,
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Returns: (gross_pnl, exit_fee, net_pnl)
        gross_pnl: 수수료 전 손익
        exit_fee: 청산 수수료
        net_pnl: 청산 수수료 후 손익 (진입 수수료는 오픈 시 이미 차감됨)
        """
        if direction == "LONG":
            gross_pnl = (close_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - close_price) * quantity

        exit_fee = quantity * close_price * fee_rate
        net_pnl = gross_pnl - exit_fee

        return gross_pnl, exit_fee, net_pnl

    @staticmethod
    def _calc_liquidation_price(
        direction: str,
        entry_price: Decimal,
        leverage: int,
    ) -> Decimal:
        """
        Binance Isolated Margin 청산가 근사 (§10.2).
        LONG:  liq = entry × (1 - 1/leverage + maintenance_rate)
        SHORT: liq = entry × (1 + 1/leverage - maintenance_rate)
        """
        lev = Decimal(str(leverage))
        if direction == "LONG":
            return entry_price * (1 - (1 / lev) + MAINTENANCE_MARGIN_RATE)
        else:
            return entry_price * (1 + (1 / lev) - MAINTENANCE_MARGIN_RATE)
