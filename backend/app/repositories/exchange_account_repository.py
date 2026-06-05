from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange_account import ExchangeAccount
from app.models.enums import HealthStatusType


class ExchangeAccountRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 조회 ─────────────────────────────────────────────────────────────────────

    async def get_active_by_user(self, user_id: uuid.UUID) -> ExchangeAccount | None:
        """사용자의 활성 거래소 계좌 조회 (소프트 삭제 제외)."""
        result = await self._db.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user_id,
                ExchangeAccount.is_active.is_(True),
                ExchangeAccount.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, account_id: uuid.UUID) -> ExchangeAccount | None:
        result = await self._db.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.id == account_id,
                ExchangeAccount.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def exists_for_user(self, user_id: uuid.UUID) -> bool:
        result = await self._db.execute(
            select(ExchangeAccount.id).where(
                ExchangeAccount.user_id == user_id,
                ExchangeAccount.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    # ── 생성 ─────────────────────────────────────────────────────────────────────

    async def create(
        self,
        user_id: uuid.UUID,
        encrypted_api_key: str,
        encrypted_api_secret: str,
        encryption_iv: str,
        key_fingerprint: str,
        label: str = "Main Account",
        is_testnet: bool = True,
        permissions: list[str] | None = None,
    ) -> ExchangeAccount:
        account = ExchangeAccount(
            user_id=user_id,
            encrypted_api_key=encrypted_api_key,
            encrypted_api_secret=encrypted_api_secret,
            encryption_iv=encryption_iv,
            key_fingerprint=key_fingerprint,
            label=label,
            is_testnet=is_testnet,
            permissions=permissions or [],
        )
        self._db.add(account)
        await self._db.flush()
        return account

    # ── 수정 ─────────────────────────────────────────────────────────────────────

    async def update_health(
        self,
        account_id: uuid.UUID,
        status: HealthStatusType,
        consecutive_failures: int,
        error_message: str | None = None,
    ) -> None:
        await self._db.execute(
            update(ExchangeAccount)
            .where(ExchangeAccount.id == account_id)
            .values(
                health_status=status,
                consecutive_failures=consecutive_failures,
                last_health_check_at=datetime.now(timezone.utc),
                last_error_message=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def update_cached_balance(
        self, account_id: uuid.UUID, balance_usdt: Decimal
    ) -> None:
        await self._db.execute(
            update(ExchangeAccount)
            .where(ExchangeAccount.id == account_id)
            .values(
                cached_balance_usdt=balance_usdt,
                balance_updated_at=datetime.now(timezone.utc),
            )
        )

    async def record_failure(self, account_id: uuid.UUID, error: str) -> None:
        account = await self.get_by_id(account_id)
        if account is None:
            return
        new_count = account.consecutive_failures + 1
        new_status = (
            HealthStatusType.DISCONNECTED
            if new_count >= 3
            else HealthStatusType.DEGRADED
        )
        await self.update_health(
            account_id, new_status, new_count, error
        )

    async def reset_failures(self, account_id: uuid.UUID) -> None:
        await self.update_health(
            account_id, HealthStatusType.HEALTHY, 0
        )

    # ── 삭제 ─────────────────────────────────────────────────────────────────────

    async def soft_delete(self, account_id: uuid.UUID) -> None:
        await self._db.execute(
            update(ExchangeAccount)
            .where(ExchangeAccount.id == account_id)
            .values(
                deleted_at=datetime.now(timezone.utc),
                is_active=False,
            )
        )
