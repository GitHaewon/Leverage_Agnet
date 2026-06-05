"""
Market Data Agent — Binance Futures 실시간 시장 데이터 수집.

수집 대상:
  - OHLCV (Kline WebSocket: 1m, 5m, 15m, 1h, 4h, 1d)
  - Volume (Kline에 포함)
  - Funding Rate (REST, 5분 폴링)
  - Open Interest (REST, 5분 폴링)
  - Order Book Top-5 (WebSocket @depth5)

저장:
  - TimescaleDB: 완성된 캔들 UPSERT
  - Redis Cache: 현재가 TTL 1s, 캔들 TTL 5m
  - Redis Streams: 캔들 완성 이벤트 → 분석 파이프라인 트리거

사용법:
    from agents.market_data import MarketDataCollector, MarketDataConfig

    cfg = MarketDataConfig(symbols=["BTCUSDT", "ETHUSDT"], testnet=True)
    collector = MarketDataCollector(cfg, redis=redis_client, db_factory=db_factory)
    await collector.run_forever()
"""

from agents.market_data.collector import MarketDataCollector, MarketDataConfig
from agents.market_data.models import (
    AggregateTrade,
    CandleCloseEvent,
    FundingRateData,
    KlineData,
    OpenInterestData,
    OrderBookData,
)

__all__ = [
    "MarketDataCollector",
    "MarketDataConfig",
    "KlineData",
    "FundingRateData",
    "OpenInterestData",
    "OrderBookData",
    "AggregateTrade",
    "CandleCloseEvent",
]
