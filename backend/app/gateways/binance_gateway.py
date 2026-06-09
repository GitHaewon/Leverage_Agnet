"""
BinanceGateway — ExecutionEngine ↔ BinanceService 브릿지.

OrderGatewayProtocol을 구현해 ExecutionEngine이 실제 Binance API를 호출할 수 있게 한다.
PaperGateway와 동일한 인터페이스를 제공하므로 ExecutionEngine 수정 없이 교체 가능하다.

안전 원칙:
  1. LIVE_TRADING_ENABLED=false면 mainnet 주문을 게이트웨이 레벨에서 다시 차단 (이중 방어)
  2. API Key는 create_order() 직전에만 복호화, aclose() 직후 평문 변수 소거
  3. SL 없는 진입은 ExecutionEngine이 이미 차단하므로 여기서는 재검증하지 않음

사용:
  LIVE_TRADING_ENABLED=false (기본값) → analysis_worker가 PaperGateway 사용
  LIVE_TRADING_ENABLED=true + BINANCE_TESTNET=true  → BinanceGateway(is_testnet=True)
  LIVE_TRADING_ENABLED=true + BINANCE_TESTNET=false → BinanceGateway(is_testnet=False)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agents.execution.gateway import TAKER_FEE_RATE
from agents.execution.models import FilledOrder, OrderTicket

logger = logging.getLogger(__name__)


class BinanceGateway:
    """
    OrderGatewayProtocol 구현체.

    ExchangeAccount에 저장된 암호화 API Key를 주문 실행 직전에만 복호화한다.
    각 place_order() 호출마다 독립 DB 세션 + Binance 클라이언트를 생성 후 즉시 닫는다
    (Celery Worker는 FastAPI lifespan을 공유하지 않으므로 장기 연결 유지 불가).
    """

    def __init__(self, user_id: uuid.UUID, is_testnet: bool) -> None:
        self._user_id = user_id
        self._is_testnet = is_testnet

    async def place_order(self, ticket: OrderTicket) -> FilledOrder:
        from app.clients import BinanceAPIError, create_binance_client
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.repositories.exchange_account_repository import ExchangeAccountRepository
        from app.utils.crypto import decrypt

        # ── 계좌 조회 (DB 세션 즉시 닫기) ──────────────────────────────────────
        async with AsyncSessionLocal() as db:
            account = await ExchangeAccountRepository(db).get_active_by_user(self._user_id)

        if account is None:
            raise RuntimeError(f"No active exchange account for user {self._user_id}")

        # ── 이중 안전 게이트: mainnet 주문 + LIVE_TRADING_ENABLED=false 조합 차단 ──
        if not account.is_testnet and not settings.LIVE_TRADING_ENABLED:
            raise RuntimeError(
                "Mainnet order blocked: LIVE_TRADING_ENABLED=false. "
                "Only testnet orders are permitted."
            )

        # ── API Key 복호화 → 클라이언트 생성 → 즉시 평문 소거 ──────────────────
        api_key = decrypt(account.encrypted_api_key)
        api_secret = decrypt(account.encrypted_api_secret)
        client = create_binance_client(api_key, api_secret, account.is_testnet)
        api_key = ""    # 평문 변수 즉시 소거
        api_secret = ""

        try:
            resp = await client.create_order(
                **_ticket_to_kwargs(ticket)
            )
        except BinanceAPIError as exc:
            logger.error(
                "Binance order failed user=%s symbol=%s purpose=%s code=%s msg=%s",
                self._user_id, ticket.symbol, ticket.purpose, exc.code, exc.message,
            )
            raise
        finally:
            await client.aclose()

        logger.info(
            "Order placed user=%s symbol=%s purpose=%s order_id=%s qty=%s price=%s",
            self._user_id, ticket.symbol, ticket.purpose,
            resp.order_id, resp.executed_qty, resp.avg_price,
        )

        return _to_filled_order(ticket, resp)

    async def cancel_all_orders(self, symbol: str) -> int:
        """심볼의 오픈 주문 전체 취소. 취소된 주문 수를 반환."""
        from app.clients import BinanceAPIError, create_binance_client
        from app.core.database import AsyncSessionLocal
        from app.repositories.exchange_account_repository import ExchangeAccountRepository
        from app.utils.crypto import decrypt

        async with AsyncSessionLocal() as db:
            account = await ExchangeAccountRepository(db).get_active_by_user(self._user_id)

        if account is None:
            return 0

        api_key = decrypt(account.encrypted_api_key)
        api_secret = decrypt(account.encrypted_api_secret)
        client = create_binance_client(api_key, api_secret, account.is_testnet)
        api_key = ""
        api_secret = ""

        cancelled = 0
        try:
            open_orders = await client.get_open_orders(symbol)
            for order in open_orders:
                try:
                    await client.cancel_order(symbol=symbol, order_id=order.order_id)
                    cancelled += 1
                except BinanceAPIError as exc:
                    logger.warning(
                        "cancel_order failed order_id=%s symbol=%s: %s",
                        order.order_id, symbol, exc.message,
                    )
        finally:
            await client.aclose()

        logger.info(
            "cancel_all_orders user=%s symbol=%s cancelled=%d",
            self._user_id, symbol, cancelled,
        )
        return cancelled


# ── 변환 헬퍼 ────────────────────────────────────────────────────────────────────

def _ticket_to_kwargs(ticket: OrderTicket) -> dict[str, Any]:
    """OrderTicket → client.create_order() kwargs."""
    kwargs: dict[str, Any] = {
        "symbol": ticket.symbol,
        "side": ticket.side,
        "order_type": ticket.order_type,
        "quantity": ticket.quantity,
    }
    if ticket.order_type in ("TAKE_PROFIT_MARKET", "STOP_MARKET"):
        # TP/SL: stop_price=트리거가, reduce_only=True
        kwargs["stop_price"] = ticket.price
        kwargs["reduce_only"] = True
    elif ticket.reduce_only:
        kwargs["reduce_only"] = True
    return kwargs


def _to_filled_order(ticket: OrderTicket, resp: Any) -> FilledOrder:
    """OrderResponse → FilledOrder."""
    avg_price = (
        resp.avg_price
        if resp.avg_price and resp.avg_price > Decimal("0")
        else ticket.price
    )
    quantity = (
        resp.executed_qty
        if resp.executed_qty and resp.executed_qty > Decimal("0")
        else ticket.quantity
    )
    fee = (quantity * avg_price * TAKER_FEE_RATE).quantize(Decimal("0.00001"))

    return FilledOrder(
        exchange_order_id=str(resp.order_id),
        symbol=resp.symbol,
        purpose=ticket.purpose,
        side=resp.side,
        order_type=resp.order_type,
        quantity=quantity,
        avg_fill_price=avg_price.quantize(Decimal("0.01")),
        fee_usdt=fee,
        filled_at=datetime.now(timezone.utc),
    )
