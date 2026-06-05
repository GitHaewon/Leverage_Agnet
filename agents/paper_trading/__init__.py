"""
Paper Trading Engine — 실거래 없이 Strategy/Risk/Sizing Engine을 검증하는 환경.

사용법:
    from agents.paper_trading import PaperTradingEngine, PaperUserSettings
    from agents.risk.models import RawSignal
    from decimal import Decimal

    settings = PaperUserSettings(user_id="test")
    engine = PaperTradingEngine(initial_balance=Decimal("10000"), settings=settings)

    signal = RawSignal(...)
    result = engine.submit_signal(signal)

    closed_trades = engine.tick("BTC", Decimal("69200"))  # TP/SL 자동 체크
"""

from agents.paper_trading.engine import PaperTradingEngine
from agents.paper_trading.models import (
    PaperPosition,
    PaperTradeRecord,
    PaperUserSettings,
    SubmitSignalResult,
)
from agents.paper_trading.state import PaperAccountState

__all__ = [
    "PaperTradingEngine",
    "PaperAccountState",
    "PaperPosition",
    "PaperTradeRecord",
    "PaperUserSettings",
    "SubmitSignalResult",
]
