"""
포트폴리오 노출도 계산.

기능:
  - 전체 계좌 관리 스냅샷 (총 노출도, 증거금, 리스크)
  - 심볼별 노출도 분해
  - §2.4 단일 코인 집중도 50% 한도 체크
  - §3.3 단일 포지션 증거금 20% 한도 체크
  - §10.4 비상 잔고 감지
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from agents.portfolio.models import (
    ACCOUNT_EMERGENCY_THRESHOLD,
    MAX_SINGLE_COIN_PORTFOLIO_RATIO,
    MAX_SINGLE_POSITION_MARGIN_RATIO,
    AccountContext,
    PortfolioPosition,
    PortfolioSnapshot,
    SymbolExposure,
)


def build_snapshot(
    positions: Sequence[PortfolioPosition],
    account: AccountContext,
) -> PortfolioSnapshot:
    """포트폴리오 전체 스냅샷을 계산한다."""
    if not positions:
        return _empty_snapshot(account)

    symbol_exposures = _build_symbol_exposures(positions)

    total_notional = sum(e.notional_value for e in symbol_exposures)
    total_margin = sum(p.margin_used for p in positions)
    total_risk = sum(p.risk_usdt for p in positions)
    total_unrealized = sum(p.unrealized_pnl for p in positions)

    coin_concentrations = _calc_coin_concentrations(symbol_exposures, total_notional)
    max_coin = max(coin_concentrations, key=lambda c: coin_concentrations[c], default="")
    max_pct = coin_concentrations.get(max_coin, 0.0)

    available = account.available_balance
    margin_util = float(total_margin / available) if available > 0 else 0.0
    risk_pct = float(total_risk / available) if available > 0 else 0.0

    is_emergency = (
        available < account.initial_balance * Decimal(str(ACCOUNT_EMERGENCY_THRESHOLD))
    )

    return PortfolioSnapshot(
        available_balance=available,
        total_balance=available + total_unrealized,
        total_notional=total_notional,
        total_margin_used=total_margin,
        margin_utilization=round(margin_util, 6),
        total_risk_usdt=total_risk,
        total_risk_pct=round(risk_pct, 6),
        coin_concentrations=coin_concentrations,
        max_concentration_coin=max_coin,
        max_concentration_pct=round(max_pct, 6),
        position_count=len(positions),
        symbol_exposures=symbol_exposures,
        is_emergency=is_emergency,
    )


def check_concentration(snapshot: PortfolioSnapshot) -> tuple[bool, str]:
    """§2.4 단일 코인 집중도 50% 한도 체크."""
    limit = MAX_SINGLE_COIN_PORTFOLIO_RATIO
    for coin, pct in snapshot.coin_concentrations.items():
        if pct > limit:
            return False, (
                f"CONCENTRATION: {coin} 집중도 {pct:.1%} > 한도 {limit:.0%}"
            )
    return True, "OK"


def check_single_position_margin(
    position: PortfolioPosition,
    account: AccountContext,
) -> tuple[bool, str]:
    """§3.3 단일 포지션 증거금 20% 한도 체크."""
    if account.available_balance <= 0:
        return False, "MARGIN_CHECK: 사용 가능 잔고 없음"
    limit = Decimal(str(MAX_SINGLE_POSITION_MARGIN_RATIO))
    ratio = position.margin_used / account.available_balance
    if ratio > limit:
        return False, (
            f"MARGIN_LIMIT: {position.symbol} 증거금 비율 {float(ratio):.1%} "
            f"> 한도 {float(limit):.0%}"
        )
    return True, "OK"


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _build_symbol_exposures(
    positions: Sequence[PortfolioPosition],
) -> list[SymbolExposure]:
    total_notional = sum(p.notional_value for p in positions)

    result: list[SymbolExposure] = []
    for p in positions:
        weight = (
            float(p.notional_value / total_notional)
            if total_notional > 0 else 0.0
        )
        result.append(SymbolExposure(
            coin=p.coin,
            symbol=p.symbol,
            direction=p.direction,
            notional_value=p.notional_value,
            margin_used=p.margin_used,
            unrealized_pnl=p.unrealized_pnl,
            risk_usdt=p.risk_usdt,
            portfolio_weight=round(weight, 6),
        ))
    return result


def _calc_coin_concentrations(
    exposures: list[SymbolExposure],
    total_notional: Decimal,
) -> dict[str, float]:
    if total_notional <= 0:
        return {}
    coin_notional: dict[str, Decimal] = {}
    for e in exposures:
        coin_notional[e.coin] = coin_notional.get(e.coin, Decimal("0")) + e.notional_value
    return {
        coin: round(float(notional / total_notional), 6)
        for coin, notional in coin_notional.items()
    }


def _empty_snapshot(account: AccountContext) -> PortfolioSnapshot:
    is_emergency = (
        account.available_balance
        < account.initial_balance * Decimal(str(ACCOUNT_EMERGENCY_THRESHOLD))
    )
    return PortfolioSnapshot(
        available_balance=account.available_balance,
        total_balance=account.available_balance,
        total_notional=Decimal("0"),
        total_margin_used=Decimal("0"),
        margin_utilization=0.0,
        total_risk_usdt=Decimal("0"),
        total_risk_pct=0.0,
        coin_concentrations={},
        max_concentration_coin="",
        max_concentration_pct=0.0,
        position_count=0,
        symbol_exposures=[],
        is_emergency=is_emergency,
    )
