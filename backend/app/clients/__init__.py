"""
Binance 클라이언트 팩토리.

MOCK_TRADING_MODE=true → BinanceMockClient (API 호출 없음)
MOCK_TRADING_MODE=false → BinanceRESTClient (실제 API)
"""
from __future__ import annotations

from app.clients.binance_base import (
    AccountInfo,
    AssetBalance,
    BinanceAPIError,
    BinanceClientProtocol,
    KeyValidationResult,
    OrderResponse,
    PositionRisk,
)
from app.clients.binance_mock import BinanceMockClient
from app.clients.binance_rest import BinanceRESTClient


def create_binance_client(
    api_key: str,
    api_secret: str,
    is_testnet: bool,
) -> BinanceRESTClient | BinanceMockClient:
    """
    설정에 따라 Real 또는 Mock 클라이언트를 반환한다.

    반환값은 사용 후 aclose()를 호출해 민감 정보를 메모리에서 제거해야 한다.
    """
    from app.core.config import settings

    if settings.MOCK_TRADING_MODE:
        return BinanceMockClient()

    from app.core.config import settings as cfg
    base_url = (
        cfg.BINANCE_TESTNET_BASE_URL if is_testnet else cfg.BINANCE_MAINNET_BASE_URL
    )
    return BinanceRESTClient(api_key=api_key, api_secret=api_secret, base_url=base_url)


__all__ = [
    "create_binance_client",
    "BinanceRESTClient",
    "BinanceMockClient",
    "BinanceAPIError",
    "BinanceClientProtocol",
    "AccountInfo",
    "AssetBalance",
    "KeyValidationResult",
    "OrderResponse",
    "PositionRisk",
]
