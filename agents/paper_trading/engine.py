"""
PaperTradingEngine — 최상위 오케스트레이터.

Strategy / Risk / Sizing Engine을 실거래 없이 검증하는 단일 진입점.

사용 패턴:
    engine = PaperTradingEngine(initial_balance=Decimal("10000"), settings=settings)

    # 시그널 제출
    result = engine.submit_signal(signal)

    # 가격 피드 (5분봉 캔들 close 등)
    closed_trades = engine.tick("BTC", Decimal("69200"))

    # 수동 청산
    trade = engine.close_position(position_id, current_price)

    # 부분 청산 (50%)
    pos, trade = engine.partial_close(position_id, current_price, ratio=0.5)

    # 요약
    print(engine.get_summary())
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional, Tuple

from agents.risk.models import RawSignal
from agents.paper_trading.models import (
    PaperPosition,
    PaperTradeRecord,
    PaperUserSettings,
    SubmitSignalResult,
)
from agents.paper_trading.position_manager import PositionManager
from agents.paper_trading.risk_engine import PaperRiskEngine
from agents.paper_trading.state import PaperAccountState

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """
    Paper Trading Engine 최상위 오케스트레이터.

    실거래 없이 Strategy/Risk/Sizing Engine의 동작을 검증한다.
    Binance API 호출 없음 — 완전 in-memory 동작.
    """

    def __init__(
        self,
        initial_balance: Decimal,
        settings: PaperUserSettings,
    ) -> None:
        self._settings = settings
        self._account = PaperAccountState(
            user_id=settings.user_id,
            _balance=initial_balance,
            initial_balance=initial_balance,
        )
        self._risk = PaperRiskEngine()
        self._pm = PositionManager()

    # ── 시그널 제출 ───────────────────────────────────────────────────────────

    def submit_signal(self, signal: RawSignal) -> SubmitSignalResult:
        """
        시그널 검증 → 포지션 오픈 (or 거부).

        pre_action 처리:
          "close_existing" → 기존 포지션 먼저 청산 후 신규 오픈
          "dca"            → 기존 포지션에 DCA 적용
        """
        validation = self._risk.validate(signal, self._settings, self._account)

        if not validation.approved:
            logger.info(
                "Paper signal REJECTED %s/%s: [%s] %s",
                signal.coin, signal.direction,
                validation.rejection_code, validation.rejection_reason,
            )
            return SubmitSignalResult(
                accepted=False,
                rejection_reason=validation.rejection_reason,
                rejection_code=validation.rejection_code,
                warnings=validation.warnings,
            )

        # ── pre_action: 반전 진입 (기존 포지션 청산) ──────────────────────
        closed_trade: Optional[PaperTradeRecord] = None
        if validation.pre_action == "close_existing":
            existing = self._account.get_open_by_coin(signal.coin)
            if existing:
                closed_trade = self._pm.close_position(
                    existing, signal.entry_price, "reverse_signal", self._account, self._settings
                )
                logger.info(
                    "Paper REVERSE: closed %s/%s pos=%s at %s net_pnl=%s",
                    existing.coin, existing.direction, existing.id,
                    signal.entry_price, closed_trade.net_pnl,
                )

            # 반전 후 새로운 검증 (잔고/포지션 수 변경됨)
            validation = self._risk.validate(signal, self._settings, self._account)
            if not validation.approved:
                return SubmitSignalResult(
                    accepted=False,
                    rejection_reason=validation.rejection_reason,
                    rejection_code=validation.rejection_code,
                    warnings=validation.warnings,
                    closed_trade=closed_trade,
                )

        # ── pre_action: DCA ────────────────────────────────────────────────
        if validation.pre_action == "dca":
            existing = self._account.get_open_by_coin(signal.coin)
            if existing:
                updated = self._pm.apply_dca(
                    existing, signal, validation, self._account, self._settings
                )
                logger.info(
                    "Paper DCA: %s/%s pos=%s dca_count=%d new_qty=%s avg_entry=%s",
                    signal.coin, signal.direction, existing.id,
                    updated.dca_count, updated.quantity, updated.entry_price,
                )
                return SubmitSignalResult(
                    accepted=True,
                    position=updated,
                    pre_action="dca",
                    warnings=validation.warnings,
                )

        # ── 신규 포지션 오픈 ───────────────────────────────────────────────
        position = self._pm.open_position(signal, validation, self._account, self._settings)
        logger.info(
            "Paper OPEN: %s/%s pos=%s qty=%s lev=%dx entry=%s tp=%s sl=%s",
            signal.coin, signal.direction, position.id,
            position.quantity, position.leverage,
            position.entry_price, position.take_profit, position.stop_loss,
        )

        return SubmitSignalResult(
            accepted=True,
            position=position,
            pre_action=validation.pre_action,
            warnings=validation.warnings,
            closed_trade=closed_trade,
        )

    # ── 가격 피드 (TP/SL 자동 처리) ──────────────────────────────────────────

    def tick(self, coin: str, current_price: Decimal) -> list[PaperTradeRecord]:
        """
        새 가격을 입력하면 해당 코인의 열린 포지션에서 TP/SL을 체크한다.

        Returns:
            이번 tick에서 청산된 TradeRecord 목록 (보통 0~1개)
        """
        closed: list[PaperTradeRecord] = []

        for position in list(self._account.open_positions.values()):
            if position.coin != coin:
                continue

            hit = self._pm.update_price(position, current_price)
            if hit:
                record = self._pm.close_position(
                    position, current_price, hit, self._account, self._settings
                )
                closed.append(record)
                logger.info(
                    "Paper AUTO-CLOSE %s %s/%s at %s net_pnl=%s reason=%s",
                    position.id, coin, position.direction,
                    current_price, record.net_pnl, hit,
                )

        return closed

    # ── 수동 전량 청산 ────────────────────────────────────────────────────────

    def close_position(
        self,
        position_id: str,
        current_price: Decimal,
    ) -> Optional[PaperTradeRecord]:
        """
        포지션을 수동으로 전량 청산한다.

        Returns:
            TradeRecord (성공) | None (position_id 없음)
        """
        position = self._account.get_position(position_id)
        if position is None or not position.is_open:
            return None

        record = self._pm.close_position(
            position, current_price, "manual", self._account, self._settings
        )
        logger.info(
            "Paper MANUAL-CLOSE %s %s/%s net_pnl=%s",
            position_id, position.coin, position.direction, record.net_pnl,
        )
        return record

    # ── 부분 청산 ─────────────────────────────────────────────────────────────

    def partial_close(
        self,
        position_id: str,
        current_price: Decimal,
        ratio: float = 0.5,
    ) -> Optional[Tuple[PaperPosition, PaperTradeRecord]]:
        """
        포지션을 ratio 비율만큼 부분 청산한다.

        Args:
            ratio: 청산 비율 (기본 0.5 = 50%)

        Returns:
            (updated_position, trade_record) | None
        """
        position = self._account.get_position(position_id)
        if position is None or not position.is_open:
            return None

        updated, record = self._pm.partial_close(
            position, current_price, ratio, self._account, self._settings
        )
        logger.info(
            "Paper PARTIAL-CLOSE %s %s/%s ratio=%.0f%% net_pnl=%s",
            position_id, position.coin, position.direction, ratio * 100, record.net_pnl,
        )
        return updated, record

    # ── 포지션 현재가 갱신 (TP/SL 체크 없이) ─────────────────────────────────

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        """
        여러 코인의 현재가를 갱신한다 (unrealized PnL 계산용).
        TP/SL 트리거 없음 — tick()과 구분.

        Args:
            prices: {"BTC": Decimal("67450"), "ETH": Decimal("3500")}
        """
        for position in self._account.open_positions.values():
            if position.coin in prices:
                position.current_price = prices[position.coin]

    # ── Kill Switch ────────────────────────────────────────────────────────────

    def halt(self, reason: str = "manual") -> None:
        """자동매매 즉시 중단."""
        self._account.halt(reason)
        logger.warning("Paper trading halted: %s", reason)

    def resume(self) -> None:
        """중단 해제 (수동 재활성화)."""
        self._account.resume()
        logger.info("Paper trading resumed")

    # ── 조회 ──────────────────────────────────────────────────────────────────

    @property
    def account(self) -> PaperAccountState:
        return self._account

    def get_open_positions(self) -> list[PaperPosition]:
        return list(self._account.open_positions.values())

    def get_trade_history(self) -> list[PaperTradeRecord]:
        return list(self._account.trade_history)

    def get_summary(self) -> dict:
        """계좌 요약 + 성과 지표."""
        history = self._account.trade_history
        open_positions = self.get_open_positions()

        wins = [t for t in history if t.net_pnl > 0 and not t.is_partial]
        losses = [t for t in history if t.net_pnl < 0 and not t.is_partial]
        full_trades = [t for t in history if not t.is_partial]

        total_pnl = sum(t.net_pnl for t in history)
        avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else Decimal("0")
        avg_loss = sum(abs(t.net_pnl) for t in losses) / len(losses) if losses else Decimal("0")
        profit_factor = (
            sum(t.net_pnl for t in wins) / sum(abs(t.net_pnl) for t in losses)
            if losses and wins
            else Decimal("0")
        )

        unrealized = sum(p.unrealized_pnl for p in open_positions)

        return {
            "account": self._account.summary(),
            "performance": {
                "total_closed_trades": len(full_trades),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate": len(wins) / len(full_trades) if full_trades else 0,
                "total_pnl": float(total_pnl),
                "unrealized_pnl": float(unrealized),
                "avg_win": float(avg_win),
                "avg_loss": float(avg_loss),
                "profit_factor": float(profit_factor),
                "return_pct": float(total_pnl / self._account.initial_balance * 100),
            },
            "open_positions": [
                {
                    "id": p.id,
                    "coin": p.coin,
                    "direction": p.direction,
                    "entry": float(p.entry_price),
                    "current": float(p.current_price),
                    "qty": float(p.quantity),
                    "leverage": p.leverage,
                    "unrealized_pnl": float(p.unrealized_pnl),
                    "pnl_pct": float(p.pnl_pct),
                    "tp": float(p.take_profit),
                    "sl": float(p.stop_loss),
                }
                for p in open_positions
            ],
        }
