"""
Binance Futures REST API 클라이언트.

보안 원칙:
  - API Secret은 서명 직후 메모리에서 참조를 제거할 것
  - 로그에 API Key/Secret 절대 출력 금지
  - Testnet과 Mainnet URL 명시적 분리
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from app.clients.binance_base import (
    AccountInfo,
    AssetBalance,
    BinanceAPIError,
    BinanceClientProtocol,
    KeyValidationResult,
    OrderResponse,
    PositionRisk,
)

logger = logging.getLogger(__name__)

_RECV_WINDOW = 5000   # 5초 타임윈도우 (Binance 기본 5000ms)


def _sign(params: dict, secret: str) -> str:
    """HMAC-SHA256 서명 생성."""
    query_string = urlencode(params)
    return hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _timestamp() -> int:
    return int(time.time() * 1000)


def _mask_key(key: str) -> str:
    """로그용 Key 마스킹 — 앞 4자리만 표시."""
    return f"{key[:4]}****" if len(key) > 4 else "****"


class BinanceRESTClient:
    """
    Binance USDT-M Futures REST API 클라이언트.

    주의: api_secret은 이 클래스가 살아있는 동안 메모리에 유지됨.
    사용 후 BinanceService에서 클라이언트 인스턴스를 즉시 폐기할 것.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-MBX-APIKEY": self._api_key},
            timeout=httpx.Timeout(10.0),
        )
        logger.debug("BinanceRESTClient initialized key=%s", _mask_key(self._api_key))

    async def _get(self, path: str, params: dict | None = None, signed: bool = False) -> dict:
        p = dict(params or {})
        if signed:
            p["timestamp"] = _timestamp()
            p["recvWindow"] = _RECV_WINDOW
            p["signature"] = _sign(p, self._api_secret)
        try:
            resp = await self._client.get(path, params=p)
            return self._parse(resp)
        except httpx.RequestError as exc:
            raise BinanceAPIError(-1000, f"Network error: {exc}") from exc

    async def _post(self, path: str, params: dict | None = None) -> dict:
        p = dict(params or {})
        p["timestamp"] = _timestamp()
        p["recvWindow"] = _RECV_WINDOW
        p["signature"] = _sign(p, self._api_secret)
        try:
            resp = await self._client.post(path, data=p)
            return self._parse(resp)
        except httpx.RequestError as exc:
            raise BinanceAPIError(-1000, f"Network error: {exc}") from exc

    async def _delete(self, path: str, params: dict | None = None) -> dict:
        p = dict(params or {})
        p["timestamp"] = _timestamp()
        p["recvWindow"] = _RECV_WINDOW
        p["signature"] = _sign(p, self._api_secret)
        try:
            resp = await self._client.delete(path, params=p)
            return self._parse(resp)
        except httpx.RequestError as exc:
            raise BinanceAPIError(-1000, f"Network error: {exc}") from exc

    @staticmethod
    def _parse(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except Exception:
            raise BinanceAPIError(-1000, f"Invalid JSON response: {response.text[:200]}")
        if isinstance(data, dict) and "code" in data and data["code"] < 0:
            raise BinanceAPIError(data["code"], data.get("msg", "Unknown error"))
        return data

    # ── 계좌 정보 ────────────────────────────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        data = await self._get("/fapi/v2/account", signed=True)
        assets = [
            AssetBalance(
                asset=a["asset"],
                wallet_balance=Decimal(a["walletBalance"]),
                unrealized_profit=Decimal(a["unrealizedProfit"]),
                margin_balance=Decimal(a["marginBalance"]),
                available_balance=Decimal(a["availableBalance"]),
            )
            for a in data.get("assets", [])
        ]
        return AccountInfo(
            total_wallet_balance=Decimal(data["totalWalletBalance"]),
            total_unrealized_profit=Decimal(data["totalUnrealizedProfit"]),
            total_margin_balance=Decimal(data["totalMarginBalance"]),
            available_balance=Decimal(data["availableBalance"]),
            total_position_initial_margin=Decimal(data["totalPositionInitialMargin"]),
            assets=assets,
            can_trade=data.get("canTrade", True),
            can_deposit=data.get("canDeposit", True),
            can_withdraw=data.get("canWithdraw", False),
        )

    async def get_balance(self) -> list[AssetBalance]:
        data = await self._get("/fapi/v2/balance", signed=True)
        return [
            AssetBalance(
                asset=b["asset"],
                wallet_balance=Decimal(b["walletBalance"]),
                unrealized_profit=Decimal(b["crossUnPnl"]),
                margin_balance=Decimal(b["marginBalance"]),
                available_balance=Decimal(b["availableBalance"]),
            )
            for b in data
        ]

    async def validate_api_key(self) -> KeyValidationResult:
        """API Key 권한 검증 — Futures account endpoint 사용."""
        try:
            account = await self.get_account_info()
            # USDT 잔고 추출
            usdt_balance = Decimal("0")
            for asset in account.assets:
                if asset.asset == "USDT":
                    usdt_balance = asset.available_balance
                    break

            return KeyValidationResult(
                can_trade=account.can_trade,
                can_futures_trade=account.can_trade,
                has_withdraw=account.can_withdraw,
                ip_restrict=False,    # Futures API에서 직접 조회 불가
                balance_usdt=usdt_balance,
            )
        except BinanceAPIError as exc:
            logger.warning(
                "API key validation failed code=%s msg=%s key=%s",
                exc.code, exc.message, _mask_key(self._api_key),
            )
            raise

    # ── 포지션 ──────────────────────────────────────────────────────────────────

    async def get_positions(self, symbol: str | None = None) -> list[PositionRisk]:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._get("/fapi/v2/positionRisk", params=params, signed=True)
        positions = []
        for p in data:
            amt = Decimal(p["positionAmt"])
            if amt == 0:
                continue    # 빈 포지션 제외
            positions.append(
                PositionRisk(
                    symbol=p["symbol"],
                    position_amt=amt,
                    entry_price=Decimal(p["entryPrice"]),
                    mark_price=Decimal(p["markPrice"]),
                    unrealized_profit=Decimal(p["unRealizedProfit"]),
                    liquidation_price=Decimal(p.get("liquidationPrice", "0")),
                    leverage=int(p["leverage"]),
                    margin_type=p.get("marginType", "cross"),
                    isolated_margin=Decimal(p.get("isolatedMargin", "0")),
                    notional=Decimal(p.get("notional", "0")),
                )
            )
        return positions

    async def get_current_price(self, symbol: str) -> Decimal:
        data = await self._get("/fapi/v1/premiumIndex", params={"symbol": symbol})
        return Decimal(data["markPrice"])

    # ── 레버리지 설정 ────────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        data = await self._post(
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
        )
        return int(data["leverage"])

    # ── 주문 ─────────────────────────────────────────────────────────────────────

    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> OrderResponse:
        params: dict = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
        }
        if price is not None:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
        if stop_price is not None:
            params["stopPrice"] = str(stop_price)
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        else:
            params["newClientOrderId"] = f"tc_{uuid.uuid4().hex[:16]}"

        data = await self._post("/fapi/v1/order", params=params)
        return self._parse_order(data)

    async def cancel_order(self, symbol: str, order_id: str) -> OrderResponse:
        data = await self._delete(
            "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
        )
        return self._parse_order(data)

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResponse]:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._get("/fapi/v1/openOrders", params=params, signed=True)
        return [self._parse_order(o) for o in data]

    @staticmethod
    def _parse_order(data: dict) -> OrderResponse:
        return OrderResponse(
            order_id=str(data["orderId"]),
            client_order_id=data.get("clientOrderId", ""),
            symbol=data["symbol"],
            status=data["status"],
            side=data["side"],
            order_type=data["type"],
            orig_qty=Decimal(data.get("origQty", "0")),
            executed_qty=Decimal(data.get("executedQty", "0")),
            avg_price=Decimal(data["avgPrice"]) if data.get("avgPrice", "0") != "0" else None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        # 민감 데이터 참조 제거
        self._api_secret = ""
        self._api_key = ""
