from __future__ import annotations

import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Cookie, Depends, Request
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.core.security import decode_access_token
from app.models.user import User
from app.utils.exceptions import UnauthorizedError

# ── 기본 인프라 의존성 ────────────────────────────────────────────────────────────
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


# ── 현재 사용자 의존성 ────────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> User:
    """
    Authorization: Bearer <token> 헤더에서 JWT 추출 → User 반환.
    인증 실패 시 401 UnauthorizedError 발생.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError(code="AUTH_004", message="인증 토큰이 없습니다.")

    token = auth_header[len("Bearer "):]

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise UnauthorizedError(code="AUTH_004", message="토큰이 만료되었거나 유효하지 않습니다.")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedError(code="AUTH_004", message="토큰 형식이 올바르지 않습니다.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedError(code="AUTH_004", message="토큰 형식이 올바르지 않습니다.")

    # 순환 import 방지를 위해 함수 내 import
    from app.services.auth_service import AuthService
    svc = AuthService(db=db, redis=redis)
    user = await svc.get_user_by_id(user_id)

    if user is None or user.deleted_at is not None:
        raise UnauthorizedError(code="AUTH_004", message="존재하지 않는 사용자입니다.")

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
