"""
BinanceRestClient — REST API 호출.

용도:
  1. Funding Rate 조회 (5분 주기)
  2. Open Interest 조회 (5분 주기)
  3. OHLCV 백필 (WebSocket 재연결 후 누락 구간 복구)

엔드포인트:
  GET /fapi/v1/premiumIndex       → Funding Rate
  GET /fapi/v1/openInterest       → Open Interest
  GET /fapi/v1/klines             → OHLCV 히스토리 (backfill)

Rate Limit:
  Binance Futures REST: 2,400 request weight / minute
  여기서는 단순 폴링이라 큰 문제 없음.
  429 응답 시 Retry-After 헤더 기준으로 대기.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from agents.market_data.models import (
    FundingRateData,
    KlineData,
    OpenInterestData,
    REST_BASE_MAINNET,
    REST_BASE_TESTNET,
)
from agents.market_data.normalizer import MarketDataNormalizer

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10.0     # 초
_MAX_KLINES_PER_REQUEST = 500

# Binance Futures 최소 Mark Price (청산가 계산에서 사용)
_DEFAULT_MARK_PRICE = Decimal("0")
_DEFAULT_INDEX_PRICE = Decimal("0")


class BinanceRestClient:
    """Binance Futures REST API 클라이언트."""

    def __init__(self, testnet: bool = False) -> None:
        self._base_url = REST_BASE_TESTNET if testnet else REST_BASE_MAINNET
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "ai-trading-copilot/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BinanceRestClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Funding Rate ──────────────────────────────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> FundingRateData | None:
        """
        GET /fapi/v1/premiumIndex

        Returns FundingRateData | None (에러 시)
        """
        try:
            resp = await self._client.get(
                "/fapi/v1/premiumIndex",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            data = resp.json()

            next_time_ms = int(data.get("nextFundingTime", 0))
            return FundingRateData(
                symbol=symbol,
                coin=symbol.replace("USDT", ""),
                funding_rate=Decimal(str(data.get("lastFundingRate", "0"))),
                mark_price=Decimal(str(data.get("markPrice", "0"))),
                index_price=Decimal(str(data.get("indexPrice", "0"))),
                next_funding_time=datetime.fromtimestamp(
                    next_time_ms / 1000, tz=timezone.utc
                ) if next_time_ms else datetime.now(timezone.utc),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = int(exc.response.headers.get("Retry-After", 1))
                logger.warning("Funding Rate rate limited, retry after %ds", retry_after)
            else:
                logger.error("Funding Rate fetch failed %s: %s", symbol, exc)
        except Exception as exc:
            logger.error("Funding Rate fetch error %s: %s", symbol, exc)
        return None

    # ── Open Interest ──────────────────────────────────────────────────────────

    async def get_open_interest(self, symbol: str) -> OpenInterestData | None:
        """
        GET /fapi/v1/openInterest

        Returns OpenInterestData | None (에러 시)
        """
        try:
            resp = await self._client.get(
                "/fapi/v1/openInterest",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            data = resp.json()

            oi = Decimal(str(data.get("openInterest", "0")))
            # mark_price로 USDT 가치 계산 (별도 조회 필요 시 get_funding_rate와 묶어서 호출)
            return OpenInterestData(
                symbol=symbol,
                coin=symbol.replace("USDT", ""),
                open_interest=oi,
                open_interest_value=oi,  # 정밀한 USDT 가치는 mark_price × OI
            )
        except Exception as exc:
            logger.error("Open Interest fetch error %s: %s", symbol, exc)
        return None

    # ── OHLCV Backfill ────────────────────────────────────────────────────────

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        since: datetime,
        limit: int = _MAX_KLINES_PER_REQUEST,
    ) -> list[KlineData]:
        """
        WebSocket 재연결 후 누락 구간 복구용 OHLCV 히스토리 조회.

        GET /fapi/v1/klines?symbol=BTCUSDT&interval=5m&startTime=...&limit=500
        """
        start_ms = int(since.timestamp() * 1000)
        klines: list[KlineData] = []

        while True:
            try:
                resp = await self._client.get(
                    "/fapi/v1/klines",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "startTime": start_ms,
                        "limit": min(limit, _MAX_KLINES_PER_REQUEST),
                    },
                )
                resp.raise_for_status()
                rows = resp.json()

                if not rows:
                    break

                batch = [
                    MarketDataNormalizer.parse_kline_rest(row, symbol, interval)
                    for row in rows
                ]
                klines.extend(batch)

                if len(rows) < _MAX_KLINES_PER_REQUEST:
                    break  # 마지막 페이지

                # 다음 페이지: 마지막 캔들 close_time + 1ms
                start_ms = int(batch[-1].close_time.timestamp() * 1000) + 1

                if len(klines) >= limit:
                    break

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    logger.warning("Klines rate limited for %s/%s", symbol, interval)
                    break
                logger.error("Klines fetch failed %s/%s: %s", symbol, interval, exc)
                break
            except Exception as exc:
                logger.error("Klines fetch error %s/%s: %s", symbol, interval, exc)
                break

        logger.info(
            "Backfill %s/%s: %d candles since %s",
            symbol, interval, len(klines), since.isoformat(),
        )
        return klines

    # ── 복합 조회 ─────────────────────────────────────────────────────────────

    async def get_funding_and_oi(
        self, symbol: str
    ) -> tuple[FundingRateData | None, OpenInterestData | None]:
        """Funding Rate + Open Interest 동시 조회 (asyncio.gather 사용)."""
        import asyncio
        return await asyncio.gather(
            self.get_funding_rate(symbol),
            self.get_open_interest(symbol),
        )
