from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OHLCV(Base):
    """
    TimescaleDB 하이퍼테이블 — 시계열 OHLCV 데이터.

    PK는 (time, coin, interval) 복합 — UUID 없음.
    마이그레이션에서 create_hypertable() 호출 필요.
    """
    __tablename__ = "ohlcv"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, primary_key=True
    )
    coin: Mapped[str] = mapped_column(String(10), nullable=False, primary_key=True)
    interval: Mapped[str] = mapped_column(
        String(5), nullable=False, primary_key=True
    )   # '1m','5m','15m','1h','4h','1d'

    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)

    __table_args__ = (
        CheckConstraint("high >= low", name="ohlcv_high_gte_low"),
        CheckConstraint("volume >= 0", name="ohlcv_volume_non_negative"),
        # 복합 unique 인덱스 — TimescaleDB가 청크별로 관리
        Index("idx_ohlcv_coin_interval_time", "coin", "interval", "time", unique=True),
    )

    def __repr__(self) -> str:
        return f"<OHLCV {self.coin}/{self.interval} time={self.time} close={self.close}>"
