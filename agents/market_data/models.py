"""
Market Data Agent 내부 데이터 모델.

외부 의존성 없는 순수 Python dataclass.
Binance WebSocket/REST 원시 데이터와 내부 표현 사이의 계약.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final

# ── 상수 ──────────────────────────────────────────────────────────────────────

SUPPORTED_COINS: Final[list[str]] = ["BTC", "ETH"]
SUPPORTED_SYMBOLS: Final[list[str]] = ["BTCUSDT", "ETHUSDT"]
KLINE_INTERVALS: Final[list[str]] = ["1m", "5m", "15m", "1h", "4h", "1d"]

WS_BASE_MAINNET: Final[str] = "wss://fstream.binance.com/stream"
WS_BASE_TESTNET: Final[str] = "wss://stream.binancefuture.com/stream"

REST_BASE_MAINNET: Final[str] = "https://fapi.binance.com"
REST_BASE_TESTNET: Final[str] = "https://testnet.binancefuture.com"

# Redis 키 패턴
REDIS_KEY_PRICE: Final[str]     = "price:{coin}"
REDIS_KEY_KLINE: Final[str]     = "kline:{symbol}:{interval}:latest"
REDIS_KEY_FUNDING: Final[str]   = "funding:{symbol}"
REDIS_KEY_OI: Final[str]        = "oi:{symbol}"
REDIS_KEY_ORDERBOOK: Final[str] = "orderbook:{symbol}"

# Redis Streams 키
STREAM_ANALYSIS_TRIGGER: Final[str] = "stream:analysis_trigger"

# TTL (초)
TTL_PRICE    = 1
TTL_KLINE    = 300
TTL_FUNDING  = 60
TTL_OI       = 300
TTL_ORDERBOOK = 5


# ── 데이터 모델 ───────────────────────────────────────────────────────────────

@dataclass
class KlineData:
    """OHLCV 캔들 데이터."""

    symbol: str
    coin: str        # "BTC" | "ETH"
    interval: str    # "1m" | "5m" | ...
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    num_trades: int
    is_closed: bool  # True = 캔들 완성 (새 캔들 시작)

    @property
    def as_price_data(self) -> "PriceData":
        return PriceData(symbol=self.symbol, coin=self.coin, price=self.close)


@dataclass
class PriceData:
    """현재가 스냅샷 (Redis TTL 1s 캐시용)."""

    symbol: str
    coin: str
    price: Decimal
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FundingRateData:
    """Binance Futures Funding Rate."""

    symbol: str
    coin: str
    funding_rate: Decimal
    mark_price: Decimal
    index_price: Decimal
    next_funding_time: datetime
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OpenInterestData:
    """Open Interest (미결제약정)."""

    symbol: str
    coin: str
    open_interest: Decimal        # 계약 수
    open_interest_value: Decimal  # USDT 가치 (= OI × mark_price)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderBookEntry:
    price: Decimal
    quantity: Decimal


@dataclass
class OrderBookData:
    """호가창 Top-5 스냅샷."""

    symbol: str
    coin: str
    bids: list[OrderBookEntry]  # 매수 (price 내림차순)
    asks: list[OrderBookEntry]  # 매도 (price 오름차순)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def best_bid(self) -> Decimal:
        return self.bids[0].price if self.bids else Decimal("0")

    @property
    def best_ask(self) -> Decimal:
        return self.asks[0].price if self.asks else Decimal("0")

    @property
    def mid_price(self) -> Decimal:
        if not self.bids or not self.asks:
            return Decimal("0")
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.best_ask - self.best_bid


@dataclass
class AggregateTrade:
    """Aggregate Trade (체결 데이터)."""

    symbol: str
    coin: str
    price: Decimal
    quantity: Decimal
    value: Decimal           # price × quantity
    is_buyer_maker: bool     # True = 매도 주도 (seller taker)
    trade_time: datetime


@dataclass
class CandleCloseEvent:
    """Redis Streams에 발행되는 캔들 완성 이벤트 (→ 분석 파이프라인 트리거)."""

    event: str        # "candle_closed"
    coin: str
    symbol: str
    interval: str
    close_price: Decimal
    close_time: datetime

    def to_stream_dict(self) -> dict[str, str]:
        return {
            "event": self.event,
            "coin": self.coin,
            "symbol": self.symbol,
            "interval": self.interval,
            "close_price": str(self.close_price),
            "close_time": self.close_time.isoformat(),
        }
