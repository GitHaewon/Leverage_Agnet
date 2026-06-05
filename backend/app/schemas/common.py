from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:20]}"


# ── 메타 ────────────────────────────────────────────────────────────────────────

class Meta(BaseModel):
    request_id: str = Field(default_factory=_new_request_id)
    timestamp: str = Field(default_factory=_utc_now)


# ── 성공 응답 ───────────────────────────────────────────────────────────────────

class DataResponse(BaseModel, Generic[T]):
    """단일 객체 성공 응답."""
    data: T
    meta: Meta = Field(default_factory=Meta)


class PaginatedData(BaseModel, Generic[T]):
    """목록 응답 데이터 래퍼."""
    items: list[T]
    total: int
    limit: int
    offset: int
    has_next: bool


class PaginatedResponse(BaseModel, Generic[T]):
    """목록 성공 응답."""
    data: PaginatedData[T]
    meta: Meta = Field(default_factory=Meta)


# ── 에러 응답 ───────────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail
    meta: Meta = Field(default_factory=Meta)


# ── 페이지네이션 파라미터 ───────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
