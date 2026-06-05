from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.user_settings import UserSettings


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 조회 ─────────────────────────────────────────────────────────────────────

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_settings(self, user_id: uuid.UUID) -> User | None:
        """설정 정보 포함 로드 — is_onboarding_completed 판단에 필요."""
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email_with_settings(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        result = await self._db.execute(
            select(User.id).where(
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    # ── 생성 ─────────────────────────────────────────────────────────────────────

    async def create(
        self,
        email: str,
        password_hash: str,
        display_name: str | None = None,
    ) -> User:
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            display_name=display_name,
        )
        self._db.add(user)
        await self._db.flush()   # id 생성 (commit 전)
        return user

    # ── 수정 ─────────────────────────────────────────────────────────────────────

    async def update_fields(
        self,
        user_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        """지정 필드만 업데이트 — ORM 객체 로드 없이 실행."""
        fields["updated_at"] = datetime.now(timezone.utc)
        await self._db.execute(
            update(User)
            .where(User.id == user_id)
            .values(**fields)
        )

    async def increment_login_attempts(self, user_id: uuid.UUID) -> int:
        """실패 카운트 증가 후 현재 값 반환."""
        user = await self.get_by_id(user_id)
        if user is None:
            return 0
        new_count = user.login_attempts + 1
        await self.update_fields(user_id, login_attempts=new_count)
        return new_count

    async def reset_login_attempts(self, user_id: uuid.UUID) -> None:
        await self.update_fields(user_id, login_attempts=0, locked_until=None)

    async def mark_email_verified(self, user_id: uuid.UUID) -> None:
        await self.update_fields(
            user_id,
            is_email_verified=True,
            email_verify_token=None,
            email_verify_expires_at=None,
        )

    async def set_verify_token(
        self, user_id: uuid.UUID, token: str, expires_at: datetime
    ) -> None:
        await self.update_fields(
            user_id,
            email_verify_token=token,
            email_verify_expires_at=expires_at,
        )

    async def update_last_login(
        self, user_id: uuid.UUID, ip_address: str | None
    ) -> None:
        await self.update_fields(
            user_id,
            last_login_at=datetime.now(timezone.utc),
            last_login_ip=ip_address,
        )

    async def update_password(
        self, user_id: uuid.UUID, password_hash: str
    ) -> None:
        await self.update_fields(
            user_id,
            password_hash=password_hash,
            password_changed_at=datetime.now(timezone.utc),
        )

    async def set_totp(
        self,
        user_id: uuid.UUID,
        encrypted_secret: str,
        backup_codes_hashed: list[str],
    ) -> None:
        await self.update_fields(
            user_id,
            totp_secret_encrypted=encrypted_secret,
            totp_backup_codes=backup_codes_hashed,
        )

    async def enable_2fa(self, user_id: uuid.UUID) -> None:
        await self.update_fields(user_id, is_2fa_enabled=True)

    async def disable_2fa(self, user_id: uuid.UUID) -> None:
        await self.update_fields(
            user_id,
            is_2fa_enabled=False,
            totp_secret_encrypted=None,
            totp_backup_codes=None,
        )

    # ── 삭제 ─────────────────────────────────────────────────────────────────────

    async def soft_delete(self, user_id: uuid.UUID) -> None:
        await self.update_fields(
            user_id, deleted_at=datetime.now(timezone.utc)
        )
