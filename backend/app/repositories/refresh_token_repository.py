from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        device_info: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device_info=device_info,
            ip_address=ip_address,
        )
        self._db.add(token)
        await self._db.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def delete_by_hash(self, token_hash: str) -> None:
        await self._db.execute(
            delete(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def delete_all_for_user(self, user_id: uuid.UUID) -> None:
        """모든 기기에서 로그아웃 (비밀번호 재설정 시 사용)."""
        await self._db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id)
        )

    async def cleanup_expired(self) -> int:
        """만료된 토큰 정리 (Celery Beat 배치용)."""
        from datetime import timezone
        from sqlalchemy import func
        result = await self._db.execute(
            delete(RefreshToken).where(
                RefreshToken.expires_at < datetime.now(timezone.utc)
            )
        )
        return result.rowcount
