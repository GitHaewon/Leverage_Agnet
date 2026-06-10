"""
Trading Schemas — 자동매매 재개 API 요청/응답 타입.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TradingResumeData(BaseModel):
    """POST /trading/resume 성공 응답 데이터."""
    is_trading_active: bool
    resumed_at: datetime
    message: str
