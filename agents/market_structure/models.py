"""
Market Structure Agent 데이터 모델.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

MARKET_STRUCTURE_WEIGHTS: dict[str, float] = {
    "funding_rate": 0.35,
    "oi_change":    0.30,
    "long_short":   0.20,
    "taker_ratio":  0.15,
}


@dataclass
class MarketStructureData:
    """Binance API에서 가져온 원시 시장 구조 데이터."""
    symbol: str
    funding_rate: float               # 현재 Funding Rate
    open_interest: float              # 현재 OI (USDT)
    open_interest_prev: float         # 1h 전 OI (OI 변화율 계산용)
    price_current: float
    price_1h_ago: float               # OI 방향 판단용
    long_short_ratio: float           # 롱/숏 비율
    long_account_pct: float           # 롱 포지션 보유 계좌 비율 (%)
    taker_long_short_ratio: float     # Taker 매수/매도 비율
    whale_volume_usdt: float = 0.0    # 500K+ 거래 누적 (1h)


@dataclass
class MarketStructureResult:
    """Market Structure Agent 분석 결과."""
    coin: str
    symbol: str
    market_score: float               # 종합 점수 (-1.0 ~ +1.0)

    # 세부 점수
    funding_score: float
    oi_score: float
    long_short_score: float
    taker_score: float

    # 원시 데이터
    funding_rate: float
    oi_1h_change_pct: float
    long_short_ratio: float
    long_account_pct: float
    whale_activity: Literal["accumulating", "distributing", "neutral"]
    market_regime: Literal["bullish_structure", "bearish_structure", "ranging"]

    @classmethod
    def neutral(cls, coin: str, symbol: str) -> "MarketStructureResult":
        return cls(
            coin=coin, symbol=symbol,
            market_score=0.0,
            funding_score=0.0, oi_score=0.0,
            long_short_score=0.0, taker_score=0.0,
            funding_rate=0.0, oi_1h_change_pct=0.0,
            long_short_ratio=1.0, long_account_pct=50.0,
            whale_activity="neutral", market_regime="ranging",
        )
