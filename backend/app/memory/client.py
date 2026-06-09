"""
Memory Layer — Qdrant 클라이언트 + 임베딩 모델 싱글톤.

AsyncQdrantClient: 비동기 벡터 저장/검색
TextEmbedding:    다국어 FastEmbed (한국어 지원, 동기)

임베딩 생성은 스레드 안전 싱글톤으로 초기화 지연(lazy init).
Qdrant 연결은 요청 당 재사용 (HTTP/2 keep-alive).
"""
from __future__ import annotations

import logging

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient

from app.core.config import settings

logger = logging.getLogger(__name__)

_qdrant_client: AsyncQdrantClient | None = None
_embedder: TextEmbedding | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """AsyncQdrantClient 싱글톤을 반환한다."""
    global _qdrant_client
    if _qdrant_client is None:
        kwargs: dict = {"url": settings.QDRANT_URL}
        if settings.QDRANT_API_KEY:
            kwargs["api_key"] = settings.QDRANT_API_KEY
        _qdrant_client = AsyncQdrantClient(**kwargs)
        logger.info("Qdrant client initialized: %s", settings.QDRANT_URL)
    return _qdrant_client


def get_embedder() -> TextEmbedding:
    """
    TextEmbedding 싱글톤을 반환한다.

    최초 호출 시 모델 가중치를 다운로드한다 (수십 초 소요 가능).
    워커 프로세스 시작 시 warm-up 권장.
    """
    global _embedder
    if _embedder is None:
        logger.info("Loading embedding model: %s", settings.MEMORY_EMBEDDING_MODEL)
        _embedder = TextEmbedding(model_name=settings.MEMORY_EMBEDDING_MODEL)
        logger.info("Embedding model loaded.")
    return _embedder


def embed_text(text: str) -> list[float]:
    """단일 텍스트를 벡터로 변환한다."""
    embedder = get_embedder()
    vectors = list(embedder.embed([text]))
    return vectors[0].tolist()


async def close_qdrant_client() -> None:
    """애플리케이션 종료 시 Qdrant 연결을 닫는다."""
    global _qdrant_client
    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None
