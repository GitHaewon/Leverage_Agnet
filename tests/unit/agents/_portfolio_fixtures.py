"""
Portfolio Manager 테스트 공통 픽스처 헬퍼.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from agents.portfolio.models import AccountContext, PortfolioPosition


def make_position(
    *,
    id: str = "pos-001",
    coin: str = "BTC",
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    entry: float = 67000.0,
    current: float = 67000.0,
    sl: float = 66000.0,
    qty: float = 0.01,
    leverage: int = 5,
    margin: float = 134.0,
    upnl: float = 0.0,
) -> PortfolioPosition:
    return PortfolioPosition(
        id=id,
        coin=coin,
        symbol=symbol,
        direction=direction,
        entry_price=Decimal(str(entry)),
        current_price=Decimal(str(current)),
        stop_loss=Decimal(str(sl)),
        quantity=Decimal(str(qty)),
        leverage=leverage,
        margin_used=Decimal(str(margin)),
        unrealized_pnl=Decimal(str(upnl)),
    )


def make_account(
    *,
    balance: float = 10000.0,
    initial: float = 10000.0,
    profile: str = "moderate",
) -> AccountContext:
    return AccountContext(
        available_balance=Decimal(str(balance)),
        initial_balance=Decimal(str(initial)),
        risk_profile=profile,
    )


def make_btc_long(
    *,
    entry: float = 67000.0,
    current: float = 67000.0,
    sl: float = 66000.0,
    qty: float = 0.01,
    leverage: int = 5,
    margin: float = 134.0,
    upnl: float = 0.0,
) -> PortfolioPosition:
    return make_position(
        id="btc-001", coin="BTC", symbol="BTCUSDT", direction="LONG",
        entry=entry, current=current, sl=sl,
        qty=qty, leverage=leverage, margin=margin, upnl=upnl,
    )


def make_btc_short(
    *,
    entry: float = 67000.0,
    current: float = 67000.0,
    sl: float = 68000.0,
    qty: float = 0.01,
    leverage: int = 5,
    margin: float = 134.0,
    upnl: float = 0.0,
) -> PortfolioPosition:
    return make_position(
        id="btc-001", coin="BTC", symbol="BTCUSDT", direction="SHORT",
        entry=entry, current=current, sl=sl,
        qty=qty, leverage=leverage, margin=margin, upnl=upnl,
    )


def make_eth_long(
    *,
    entry: float = 3500.0,
    current: float = 3500.0,
    sl: float = 3400.0,
    qty: float = 0.1,
    leverage: int = 5,
    margin: float = 70.0,
    upnl: float = 0.0,
) -> PortfolioPosition:
    return make_position(
        id="eth-001", coin="ETH", symbol="ETHUSDT", direction="LONG",
        entry=entry, current=current, sl=sl,
        qty=qty, leverage=leverage, margin=margin, upnl=upnl,
    )


def make_eth_short(
    *,
    entry: float = 3500.0,
    current: float = 3500.0,
    sl: float = 3600.0,
    qty: float = 0.1,
    leverage: int = 5,
    margin: float = 70.0,
    upnl: float = 0.0,
) -> PortfolioPosition:
    return make_position(
        id="eth-001", coin="ETH", symbol="ETHUSDT", direction="SHORT",
        entry=entry, current=current, sl=sl,
        qty=qty, leverage=leverage, margin=margin, upnl=upnl,
    )
