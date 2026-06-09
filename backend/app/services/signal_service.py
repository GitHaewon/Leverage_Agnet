"""
Signal Service — signal lifecycle management.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.enums import SignalStatusType
from app.models.signal import Signal


async def expire_old_signals() -> int:
    """Mark active signals whose expires_at has passed as expired. Returns row count."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        stmt = (
            update(Signal)
            .where(Signal.status == SignalStatusType.ACTIVE)
            .where(Signal.expires_at <= now)
            .values(status=SignalStatusType.EXPIRED)
            .execution_options(synchronize_session=False)
        )
        result = await db.execute(stmt)
        await db.commit()
    return result.rowcount
