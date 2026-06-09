"""
Memory Layer — MemoryStore: Qdrant upsert 연산.

역할: ORM 모델 → 문서 변환 → 임베딩 → Qdrant 저장

upsert는 멱등(idempotent) — 동일 position_id로 재호출 시 벡터를 갱신한다.
포지션 종료 직후 Celery task에서 비동기로 호출한다.
"""
from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from app.memory.client import embed_text, get_qdrant_client
from app.memory.collections import (
    COLLECTION_JOURNALS,
    COLLECTION_REFLECTIONS,
    COLLECTION_STRATEGY,
    ensure_collections,
)
from app.memory.documents import JournalDocument, ReflectionDocument, StrategyDocument
from app.models.reflection_report import ReflectionReport
from app.models.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    Qdrant 세 컬렉션에 대한 upsert/delete 연산을 담당한다.

    생성자 주입(DI)을 지원하므로 테스트에서 Mock 클라이언트를 주입할 수 있다.
    `get_default()` 클래스 메서드로 싱글톤 클라이언트를 사용하는 인스턴스를 얻는다.
    """

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client
        self._initialized = False

    @classmethod
    def get_default(cls) -> "MemoryStore":
        return cls(client=get_qdrant_client())

    # ── 초기화 ────────────────────────────────────────────────────────────────

    async def ensure_ready(self) -> None:
        """컬렉션이 존재하지 않으면 생성한다. 한 번만 실행된다."""
        if not self._initialized:
            await ensure_collections(self._client)
            self._initialized = True

    # ── Upsert 연산 ───────────────────────────────────────────────────────────

    async def upsert_journal(self, journal: TradeJournal) -> None:
        """
        TradeJournal을 trade_journals 컬렉션과 trade_strategy 컬렉션에
        동시에 저장한다.

        Strategy 문서는 같은 포지션의 시그널 + 결과 조합이므로
        Journal이 생성될 때 함께 저장한다.
        """
        await self.ensure_ready()

        journal_doc = JournalDocument.from_orm(journal)
        strategy_doc = StrategyDocument.from_journal(journal)

        await self._upsert_points(
            COLLECTION_JOURNALS,
            journal_doc.point_id,
            journal_doc.embed_text,
            journal_doc.payload,
        )
        await self._upsert_points(
            COLLECTION_STRATEGY,
            strategy_doc.point_id,
            strategy_doc.embed_text,
            strategy_doc.payload,
        )

        logger.info(
            "upserted journal+strategy memory position=%s user=%s",
            journal.position_id, journal.user_id,
        )

    async def upsert_reflection(self, report: ReflectionReport) -> None:
        """ReflectionReport를 trade_reflections 컬렉션에 저장한다."""
        await self.ensure_ready()

        doc = ReflectionDocument.from_orm(report)
        await self._upsert_points(
            COLLECTION_REFLECTIONS,
            doc.point_id,
            doc.embed_text,
            doc.payload,
        )

        logger.info(
            "upserted reflection memory position=%s user=%s grade=%s",
            report.position_id, report.user_id, report.ai_grade,
        )

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    async def delete_by_position(self, position_id: str) -> None:
        """
        포지션 삭제 시 세 컬렉션에서 해당 벡터를 제거한다.

        실제 운영에서는 거의 사용되지 않는다.
        Soft Delete 원칙에 따라 삭제보다 페이로드 마킹을 권장한다.
        """
        await self.ensure_ready()
        from qdrant_client.models import PointIdsList

        for collection in [COLLECTION_JOURNALS, COLLECTION_REFLECTIONS, COLLECTION_STRATEGY]:
            await self._client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=[position_id]),
            )

        logger.info("deleted memory vectors for position=%s", position_id)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    async def _upsert_points(
        self,
        collection: str,
        point_id: str,
        text: str,
        payload: dict[str, Any],
    ) -> None:
        """텍스트를 임베딩하고 Qdrant에 upsert한다."""
        vector = embed_text(text)
        await self._client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
