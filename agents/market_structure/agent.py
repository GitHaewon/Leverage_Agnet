"""
Market Structure Agent — Binance Futures 시장 구조 분석.

실행 방식: Celery Task (Technical, Sentiment과 병렬 실행)
실행 주기: 5분
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from agents.market_structure.models import MarketStructureData, MarketStructureResult
from agents.market_structure.scorer import (
    combine_market_scores,
    determine_market_regime,
    determine_whale_activity,
    score_funding_rate,
    score_long_short,
    score_oi_change,
    score_taker_ratio,
)

logger = logging.getLogger(__name__)

REST_MAINNET = "https://fapi.binance.com"
REST_TESTNET = "https://testnet.binancefuture.com"
TIMEOUT_SECONDS = 8.0
WHALE_THRESHOLD_USDT = 500_000.0


class MarketStructureAgent:
    """Market Structure Agent.

    testnet=True이면 Binance Testnet을 사용한다.
    """

    def __init__(self, testnet: bool = True) -> None:
        self._base = REST_TESTNET if testnet else REST_MAINNET

    async def analyze(
        self,
        coin: str,
        symbol: str,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ) -> MarketStructureResult:
        """시장 구조를 분석하여 MarketStructureResult를 반환한다.

        개별 API 실패 시 해당 지표를 0.0으로 처리하고 계속 진행한다.
        """
        _client = client or httpx.AsyncClient(
            base_url=self._base, timeout=TIMEOUT_SECONDS
        )
        try:
            data = await self._fetch_all(symbol, _client)
        except Exception as exc:
            logger.warning("market_structure.fetch_failed coin=%s err=%s", coin, exc)
            return MarketStructureResult.neutral(coin, symbol)
        finally:
            if client is None:
                await _client.aclose()

        return self._score(coin, data)

    async def _fetch_all(
        self, symbol: str, client: httpx.AsyncClient
    ) -> MarketStructureData:
        import asyncio as _asyncio

        results = await _asyncio.gather(
            self._fetch_funding(symbol, client),
            self._fetch_oi(symbol, client),
            self._fetch_price(symbol, client),
            self._fetch_long_short(symbol, client),
            self._fetch_taker_ratio(symbol, client),
            return_exceptions=True,
        )

        funding: dict = results[0] if not isinstance(results[0], Exception) else {}
        oi_now: float = float(results[1]) if not isinstance(results[1], Exception) else 0.0
        prices: tuple = results[2] if not isinstance(results[2], Exception) else (0.0, 0.0)
        ls: dict = results[3] if not isinstance(results[3], Exception) else {}
        taker: dict = results[4] if not isinstance(results[4], Exception) else {}

        price_now, price_1h = prices
        oi_prev = oi_now * 0.99  # 이전 OI 근사 (TimescaleDB 없는 경우 fallback)

        return MarketStructureData(
            symbol=symbol,
            funding_rate=float(funding.get("lastFundingRate", 0.0)),
            open_interest=oi_now,
            open_interest_prev=oi_prev,
            price_current=price_now,
            price_1h_ago=price_1h or price_now * 0.99,
            long_short_ratio=float(ls.get("longShortRatio", 1.0)),
            long_account_pct=float(ls.get("longAccount", 0.5)) * 100,
            taker_long_short_ratio=float(taker.get("buySellRatio", 1.0)),
        )

    # ── Binance REST 헬퍼 ─────────────────────────────────────────────────────

    async def _fetch_funding(self, symbol: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get("/fapi/v1/premiumIndex", params={"symbol": symbol})
        resp.raise_for_status()
        return resp.json()

    async def _fetch_oi(self, symbol: str, client: httpx.AsyncClient) -> float:
        resp = await client.get("/fapi/v1/openInterest", params={"symbol": symbol})
        resp.raise_for_status()
        return float(resp.json()["openInterest"])

    async def _fetch_price(
        self, symbol: str, client: httpx.AsyncClient
    ) -> tuple[float, float]:
        """현재가와 1시간 전 종가를 반환한다."""
        resp = await client.get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1h", "limit": 2},
        )
        resp.raise_for_status()
        candles = resp.json()
        price_now = float(candles[-1][4]) if candles else 0.0
        price_1h = float(candles[-2][4]) if len(candles) >= 2 else price_now
        return price_now, price_1h

    async def _fetch_long_short(self, symbol: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(
            "/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": "5m", "limit": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    async def _fetch_taker_ratio(self, symbol: str, client: httpx.AsyncClient) -> dict:
        resp = await client.get(
            "/futures/data/takerlongshortRatio",
            params={"symbol": symbol, "period": "5m", "limit": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    # ── 점수 계산 ─────────────────────────────────────────────────────────────

    def _score(self, coin: str, data: MarketStructureData) -> MarketStructureResult:
        oi_change_pct = (
            (data.open_interest - data.open_interest_prev) / data.open_interest_prev * 100
            if data.open_interest_prev > 0 else 0.0
        )
        price_change_pct = (
            (data.price_current - data.price_1h_ago) / data.price_1h_ago * 100
            if data.price_1h_ago > 0 else 0.0
        )

        f_score = score_funding_rate(data.funding_rate)
        oi_score = score_oi_change(oi_change_pct, price_change_pct)
        ls_score = score_long_short(data.long_short_ratio)
        tk_score = score_taker_ratio(data.taker_long_short_ratio)

        combined = combine_market_scores(f_score, oi_score, ls_score, tk_score)
        whale = determine_whale_activity(data.whale_volume_usdt, price_change_pct)
        regime = determine_market_regime(combined)

        return MarketStructureResult(
            coin=coin,
            symbol=data.symbol,
            market_score=round(combined, 4),
            funding_score=round(f_score, 4),
            oi_score=round(oi_score, 4),
            long_short_score=round(ls_score, 4),
            taker_score=round(tk_score, 4),
            funding_rate=data.funding_rate,
            oi_1h_change_pct=round(oi_change_pct, 2),
            long_short_ratio=data.long_short_ratio,
            long_account_pct=data.long_account_pct,
            whale_activity=whale,
            market_regime=regime,
        )
