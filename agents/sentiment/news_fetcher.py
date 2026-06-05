"""
CryptoCompare 뉴스 패처.

CRYPTOCOMPARE_API_KEY 환경변수 필요.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

BASE_URL = "https://min-api.cryptocompare.com/data/v2/news/"
TIMEOUT_SECONDS = 8.0
_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")


async def fetch_crypto_headlines(
    coin: str,
    count: int = 20,
    api_key: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """CryptoCompare에서 최신 뉴스 헤드라인을 가져온다.

    API 키 없이도 제한된 요청 가능하나 키 있으면 더 안정적.
    실패 시 빈 리스트 반환.
    """
    key = api_key or _API_KEY
    headers = {"authorization": f"Apikey {key}"} if key else {}
    params = {
        "categories": coin,
        "excludeCategories": "Sponsored",
        "lang": "EN",
        "sortOrder": "latest",
    }

    try:
        _client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        async with _client if client is None else _noop_ctx(_client):
            resp = await _client.get(BASE_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("Data", [])[:count]
            return [a["title"] for a in articles if a.get("title")]
    except Exception:
        return []


class _noop_ctx:
    def __init__(self, obj) -> None:
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, *args) -> None:
        pass
