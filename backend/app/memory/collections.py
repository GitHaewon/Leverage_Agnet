"""
Memory Layer — Qdrant 컬렉션 정의 및 초기화.

세 가지 컬렉션:
  trade_journals    — TradeJournal 기반 (진입·청산 이유, 전략, P&L)
  trade_reflections — ReflectionReport 기반 (AI 회고, 강점·실수·개선)
  trade_strategy    — Signal + 결과 기반 (기술 점수, 감성, 시장구조 + 성과)

모든 컬렉션에 user_id, coin, is_win 페이로드 인덱스를 생성하여
사용자 격리 + 승패 필터링 쿼리 성능을 보장한다.
"""
from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── 컬렉션 이름 상수 ──────────────────────────────────────────────────────────

COLLECTION_JOURNALS = "trade_journals"
COLLECTION_REFLECTIONS = "trade_reflections"
COLLECTION_STRATEGY = "trade_strategy"

ALL_COLLECTIONS = [COLLECTION_JOURNALS, COLLECTION_REFLECTIONS, COLLECTION_STRATEGY]

# ── 페이로드 인덱스 정의 ──────────────────────────────────────────────────────
# (필드명, 스키마 타입) — 필터링에 사용되는 필드만 인덱싱

_PAYLOAD_INDEXES: dict[str, list[tuple[str, PayloadSchemaType]]] = {
    COLLECTION_JOURNALS: [
        ("user_id", PayloadSchemaType.KEYWORD),
        ("coin", PayloadSchemaType.KEYWORD),
        ("direction", PayloadSchemaType.KEYWORD),
        ("is_win", PayloadSchemaType.BOOL),
        ("close_reason", PayloadSchemaType.KEYWORD),
    ],
    COLLECTION_REFLECTIONS: [
        ("user_id", PayloadSchemaType.KEYWORD),
        ("coin", PayloadSchemaType.KEYWORD),
        ("direction", PayloadSchemaType.KEYWORD),
        ("is_win", PayloadSchemaType.BOOL),
        ("ai_grade", PayloadSchemaType.KEYWORD),
    ],
    COLLECTION_STRATEGY: [
        ("user_id", PayloadSchemaType.KEYWORD),
        ("coin", PayloadSchemaType.KEYWORD),
        ("direction", PayloadSchemaType.KEYWORD),
        ("is_win", PayloadSchemaType.BOOL),
        ("close_reason", PayloadSchemaType.KEYWORD),
    ],
}


async def ensure_collections(client: AsyncQdrantClient) -> None:
    """
    세 컬렉션이 존재하지 않으면 생성하고 페이로드 인덱스를 설정한다.

    애플리케이션 시작 시(lifespan) 또는 최초 upsert 전에 한 번 호출한다.
    이미 존재하는 컬렉션은 건드리지 않는다 (멱등).
    """
    vector_params = VectorParams(
        size=settings.MEMORY_VECTOR_SIZE,
        distance=Distance.COSINE,
    )

    for name in ALL_COLLECTIONS:
        exists = await client.collection_exists(name)
        if not exists:
            await client.create_collection(
                collection_name=name,
                vectors_config=vector_params,
            )
            logger.info("Created Qdrant collection: %s", name)

            for field_name, schema in _PAYLOAD_INDEXES[name]:
                await client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=schema,
                )
            logger.info("Created payload indexes for: %s", name)
        else:
            logger.debug("Collection already exists: %s", name)


async def drop_all_collections(client: AsyncQdrantClient) -> None:
    """테스트 환경에서만 사용 — 모든 컬렉션을 삭제한다."""
    for name in ALL_COLLECTIONS:
        if await client.collection_exists(name):
            await client.delete_collection(name)
            logger.warning("Dropped Qdrant collection: %s", name)
