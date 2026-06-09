"""
Memory Layer — MemorySearcher: 유사 거래 검색 + Claude 패턴 합성.

3가지 검색 기능:
  similar_trades   — 현재 시장 상황과 유사한 과거 거래 검색
  winning_patterns — 같은 조건에서 수익을 낸 패턴
  losing_patterns  — 같은 조건에서 손실을 낸 패턴

각 검색 후 Claude Sonnet이 결과를 분석하여
실용적인 트레이딩 인사이트를 한국어로 합성(synthesis)한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import anthropic
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, ScoredPoint

from app.core.config import settings
from app.memory.client import embed_text, get_qdrant_client
from app.memory.collections import (
    COLLECTION_JOURNALS,
    COLLECTION_REFLECTIONS,
    COLLECTION_STRATEGY,
)
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)


# ── 검색 입력 스키마 ──────────────────────────────────────────────────────────

class SearchCollection(str, Enum):
    JOURNALS = "journals"
    REFLECTIONS = "reflections"
    STRATEGY = "strategy"
    ALL = "all"


class SimilarTradeQuery(BaseModel):
    """유사 거래 검색 쿼리."""
    query_text: str = Field(description="검색 자연어 텍스트 (코인, 지표, 진입 이유 등)")
    user_id: str
    coin: str | None = None
    direction: str | None = None  # "LONG" | "SHORT"
    collection: SearchCollection = SearchCollection.JOURNALS
    limit: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class PatternQuery(BaseModel):
    """승패 패턴 검색 쿼리."""
    query_text: str
    user_id: str
    coin: str | None = None
    direction: str | None = None
    collection: SearchCollection = SearchCollection.ALL
    limit: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.4, ge=0.0, le=1.0)


# ── 검색 결과 타입 ─────────────────────────────────────────────────────────────

@dataclass
class SearchHit:
    score: float
    source: str           # "journal" | "reflection" | "strategy"
    coin: str
    direction: str
    is_win: bool
    net_pnl: float
    close_reason: str
    payload: dict[str, Any]

    @classmethod
    def from_scored_point(cls, point: ScoredPoint) -> "SearchHit":
        p = point.payload or {}
        return cls(
            score=round(point.score, 4),
            source=p.get("source", "unknown"),
            coin=p.get("coin", ""),
            direction=p.get("direction", ""),
            is_win=bool(p.get("is_win", False)),
            net_pnl=float(p.get("net_pnl", 0.0)),
            close_reason=p.get("close_reason", ""),
            payload=p,
        )


@dataclass
class TradeMemoryResult:
    hits: list[SearchHit]
    synthesis: str         # Claude Sonnet 패턴 분석 요약
    query: str
    total_found: int = field(init=False)

    def __post_init__(self) -> None:
        self.total_found = len(self.hits)

    @property
    def win_rate(self) -> float:
        if not self.hits:
            return 0.0
        wins = sum(1 for h in self.hits if h.is_win)
        return wins / len(self.hits)

    @property
    def avg_pnl(self) -> float:
        if not self.hits:
            return 0.0
        return sum(h.net_pnl for h in self.hits) / len(self.hits)


# ── Claude 합성 프롬프트 ──────────────────────────────────────────────────────

_SYNTHESIS_SYSTEM = """\
You are a professional cryptocurrency trading analyst.
Analyze the provided historical trade data and extract actionable patterns.
Respond in Korean. Keep it under 200 words. Be specific and data-driven.
"""

_SYNTHESIS_TEMPLATES = {
    "similar": "다음 유사 거래 패턴에서 핵심 인사이트를 추출하세요:",
    "winning": "다음 수익 거래들의 공통 성공 패턴을 분석하세요:",
    "losing": "다음 손실 거래들의 공통 실패 원인을 분석하고 개선 방향을 제시하세요:",
}


# ── MemorySearcher ────────────────────────────────────────────────────────────

class MemorySearcher:
    """
    Qdrant 벡터 검색 + Claude Sonnet 패턴 합성.

    사용자 격리: 모든 검색은 user_id 필터를 포함한다.
    합성 실패: Claude API 오류 시 빈 문자열 반환 (검색 결과는 보존).
    """

    def __init__(
        self,
        store: MemoryStore,
        anthropic_client: anthropic.AsyncAnthropic,
    ) -> None:
        self._store = store
        self._anthropic = anthropic_client

    @classmethod
    def get_default(cls) -> "MemorySearcher":
        store = MemoryStore.get_default()
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return cls(store=store, anthropic_client=client)

    # ── 공개 검색 API ─────────────────────────────────────────────────────────

    async def search_similar_trades(self, query: SimilarTradeQuery) -> TradeMemoryResult:
        """
        현재 시장 상황 또는 진입 조건과 유사한 과거 거래를 검색한다.

        사용 예: 시그널 생성 전 "과거에 이 상황에서 어떻게 됐나?" 조회
        """
        collections = _resolve_collections(query.collection)
        filter_must = _build_filter_conditions(
            user_id=query.user_id,
            coin=query.coin,
            direction=query.direction,
        )

        hits = await self._multi_search(
            query_text=query.query_text,
            collections=collections,
            filter_must=filter_must,
            limit=query.limit,
            score_threshold=query.score_threshold,
        )
        synthesis = await self._synthesize("similar", hits)

        return TradeMemoryResult(hits=hits, synthesis=synthesis, query=query.query_text)

    async def search_winning_patterns(self, query: PatternQuery) -> TradeMemoryResult:
        """
        수익을 낸 거래 중 현재 쿼리와 유사한 패턴을 검색한다.

        사용 예: "BTC LONG RSI 과매도 진입에서 성공한 패턴"
        """
        collections = _resolve_collections(query.collection)
        filter_must = _build_filter_conditions(
            user_id=query.user_id,
            coin=query.coin,
            direction=query.direction,
            is_win=True,
        )

        hits = await self._multi_search(
            query_text=query.query_text,
            collections=collections,
            filter_must=filter_must,
            limit=query.limit,
            score_threshold=query.score_threshold,
        )
        synthesis = await self._synthesize("winning", hits)

        return TradeMemoryResult(hits=hits, synthesis=synthesis, query=query.query_text)

    async def search_losing_patterns(self, query: PatternQuery) -> TradeMemoryResult:
        """
        손실을 낸 거래 중 현재 쿼리와 유사한 패턴을 검색한다.

        사용 예: "이 조건에서 손절난 이유와 피해야 할 패턴"
        """
        collections = _resolve_collections(query.collection)
        filter_must = _build_filter_conditions(
            user_id=query.user_id,
            coin=query.coin,
            direction=query.direction,
            is_win=False,
        )

        hits = await self._multi_search(
            query_text=query.query_text,
            collections=collections,
            filter_must=filter_must,
            limit=query.limit,
            score_threshold=query.score_threshold,
        )
        synthesis = await self._synthesize("losing", hits)

        return TradeMemoryResult(hits=hits, synthesis=synthesis, query=query.query_text)

    # ── 내부: 다중 컬렉션 검색 ────────────────────────────────────────────────

    async def _multi_search(
        self,
        query_text: str,
        collections: list[str],
        filter_must: list,
        limit: int,
        score_threshold: float,
    ) -> list[SearchHit]:
        query_vector = embed_text(query_text)
        qfilter = Filter(must=filter_must) if filter_must else None

        all_hits: list[SearchHit] = []
        client = self._store._client

        for collection in collections:
            try:
                results = await client.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    query_filter=qfilter,
                    limit=limit,
                    with_payload=True,
                    score_threshold=score_threshold,
                )
                all_hits.extend(SearchHit.from_scored_point(p) for p in results)
            except Exception as exc:
                logger.warning("search failed collection=%s: %s", collection, exc)

        # 점수 내림차순 정렬 후 limit 적용
        all_hits.sort(key=lambda h: h.score, reverse=True)
        return all_hits[:limit]

    # ── 내부: Claude 패턴 합성 ────────────────────────────────────────────────

    async def _synthesize(
        self, search_type: str, hits: list[SearchHit]
    ) -> str:
        """
        검색 결과를 Claude Sonnet에 전달하여 패턴 분석 요약을 생성한다.

        hit가 없거나 Claude API 오류 시 빈 문자열을 반환한다.
        """
        if not hits:
            return ""

        header = _SYNTHESIS_TEMPLATES.get(search_type, "다음 거래 패턴을 분석하세요:")
        hit_lines = []
        for i, h in enumerate(hits, 1):
            win_str = "✓ 수익" if h.is_win else "✗ 손실"
            pnl_sign = "+" if h.net_pnl >= 0 else ""
            hit_lines.append(
                f"{i}. {h.coin} {h.direction} | {h.close_reason} | "
                f"P&L {pnl_sign}{h.net_pnl:.2f} USDT | 유사도 {h.score:.2f} | {win_str}"
            )

        user_prompt = header + "\n\n" + "\n".join(hit_lines)

        try:
            response = await self._anthropic.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=350,
                temperature=0.3,
                system=_SYNTHESIS_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text.strip()
        except anthropic.APIStatusError as e:
            logger.warning("Claude synthesis API error: %s", e.status_code)
            return ""
        except Exception as exc:
            logger.warning("Claude synthesis failed: %s", exc)
            return ""


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _resolve_collections(collection: SearchCollection) -> list[str]:
    mapping = {
        SearchCollection.JOURNALS: [COLLECTION_JOURNALS],
        SearchCollection.REFLECTIONS: [COLLECTION_REFLECTIONS],
        SearchCollection.STRATEGY: [COLLECTION_STRATEGY],
        SearchCollection.ALL: [
            COLLECTION_JOURNALS,
            COLLECTION_REFLECTIONS,
            COLLECTION_STRATEGY,
        ],
    }
    return mapping[collection]


def _build_filter_conditions(
    *,
    user_id: str,
    coin: str | None = None,
    direction: str | None = None,
    is_win: bool | None = None,
) -> list:
    conditions = [
        FieldCondition(key="user_id", match=MatchValue(value=user_id))
    ]
    if coin:
        conditions.append(FieldCondition(key="coin", match=MatchValue(value=coin)))
    if direction:
        conditions.append(FieldCondition(key="direction", match=MatchValue(value=direction)))
    if is_win is not None:
        conditions.append(FieldCondition(key="is_win", match=MatchValue(value=is_win)))
    return conditions


# ── 쿼리 텍스트 자동 생성 헬퍼 ───────────────────────────────────────────────

def build_query_from_signal(
    coin: str,
    direction: str,
    reasons: list[str],
    tech_score: float | None = None,
    market_score: float | None = None,
) -> str:
    """
    현재 시그널 데이터로부터 메모리 검색 쿼리 텍스트를 자동 생성한다.

    Synthesis Agent에서 시그널 생성 후 유사 과거 거래를 조회할 때 사용한다.
    """
    parts = [f"{coin} {direction}"]
    if reasons:
        parts.extend(reasons[:3])
    if tech_score is not None:
        parts.append(f"기술점수 {tech_score:+.2f}")
    if market_score is not None:
        parts.append(f"시장점수 {market_score:+.2f}")
    return " | ".join(parts)
