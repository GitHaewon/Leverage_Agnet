"""
상관관계 기반 포트폴리오 리스크 계산.

BTC-ETH 상관계수(ρ=0.85)를 이용한 2자산 포트폴리오 리스크 공식:
  adjusted = sqrt(r1² + r2² + 2ρr1r2)

P&L 상관 방향:
  동일 방향 (LONG-LONG / SHORT-SHORT): ρ = +0.85  → 동시 손실 가능성 높음
  반대 방향 (LONG-SHORT):              ρ = -0.85  → 부분 헤지 효과

TRADING_RULES.md 참조:
  §3.2 — naive sum을 하드 리미트 기준으로 사용 (보수적)
  상관관계 값은 리스크 점수 페널티 및 정보 표시용
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Sequence

from agents.portfolio.models import BTC_ETH_CORRELATION, CorrelationRisk, PortfolioPosition


def calculate_correlation_risk(
    positions: Sequence[PortfolioPosition],
    btc_eth_corr: float = BTC_ETH_CORRELATION,
) -> CorrelationRisk:
    """BTC-ETH 상관관계를 반영한 포트폴리오 리스크 계산.

    단일 자산 또는 동일 코인만 있으면 adjusted = raw.
    BTC + ETH 모두 있을 때만 2자산 포트폴리오 공식 적용.
    """
    if not positions:
        return CorrelationRisk(
            raw_risk_usdt=Decimal("0"),
            adjusted_risk_usdt=Decimal("0"),
            adjustment_factor=1.0,
            correlation_coefficient=btc_eth_corr,
            pairs=[],
        )

    raw_risk = sum(p.risk_usdt for p in positions)

    btc_positions = [p for p in positions if p.coin == "BTC"]
    eth_positions = [p for p in positions if p.coin == "ETH"]

    if not btc_positions or not eth_positions:
        return CorrelationRisk(
            raw_risk_usdt=raw_risk,
            adjusted_risk_usdt=raw_risk,
            adjustment_factor=1.0,
            correlation_coefficient=btc_eth_corr,
            pairs=[],
        )

    r_btc = sum(p.risk_usdt for p in btc_positions)
    r_eth = sum(p.risk_usdt for p in eth_positions)

    # 동일 방향 → 양의 상관 (동시 손실), 반대 방향 → 음의 상관 (헤지)
    btc_dir = btc_positions[0].direction
    eth_dir = eth_positions[0].direction
    effective_rho = btc_eth_corr if btc_dir == eth_dir else -btc_eth_corr

    adjusted = _calc_2asset_risk(float(r_btc), float(r_eth), effective_rho)

    raw_float = float(raw_risk)
    factor = adjusted / raw_float if raw_float > 0 else 1.0

    return CorrelationRisk(
        raw_risk_usdt=raw_risk,
        adjusted_risk_usdt=Decimal(str(round(adjusted, 4))),
        adjustment_factor=round(factor, 4),
        correlation_coefficient=btc_eth_corr,
        pairs=[(btc_dir, btc_dir, eth_dir, eth_dir, round(effective_rho, 4))],
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _calc_2asset_risk(r1: float, r2: float, rho: float) -> float:
    """2자산 포트폴리오 리스크: sqrt(r1² + r2² + 2ρr1r2).

    floating point 보호: variance가 음수가 되지 않도록 max(0) 적용.
    """
    variance = r1 ** 2 + r2 ** 2 + 2 * rho * r1 * r2
    return math.sqrt(max(variance, 0.0))
