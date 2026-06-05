"""
Fear & Greed Index 클라이언트 (Alternative.me API).

공개 API — 인증 불필요.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from agents.sentiment.models import FearGreedData
from agents.sentiment.scorer import normalize_fear_greed, label_fear_greed

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1&format=json"
TIMEOUT_SECONDS = 5.0


async def fetch_fear_greed(
    client: Optional[httpx.AsyncClient] = None,
) -> FearGreedData:
    """Fear & Greed Index를 가져온다.

    실패 시 Neutral(50)을 반환한다.
    """
    try:
        _client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        async with _client if client is None else _noop_ctx(_client):
            resp = await _client.get(FEAR_GREED_URL)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            item = data["data"][0]
            index = int(item["value"])
            return FearGreedData(
                index=index,
                label=item.get("value_classification", label_fear_greed(index)),
                score=normalize_fear_greed(index),
            )
    except Exception:
        return FearGreedData(index=50, label="Neutral", score=0.0)


class _noop_ctx:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    async def __aenter__(self) -> Any:
        return self._obj

    async def __aexit__(self, *args: Any) -> None:
        pass
