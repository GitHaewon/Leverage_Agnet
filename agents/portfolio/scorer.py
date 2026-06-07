"""
포트폴리오 종합 리스크 점수 계산.

점수 = 4개 컴포넌트 가중합 (0.0~1.0):
  portfolio_risk_ratio  × 0.40  — §3.2 총 리스크 / 한도
  concentration_ratio   × 0.25  — §2.4 최대 코인 집중도 / 50%
  correlation_penalty   × 0.20  — 동일 방향 BTC-ETH 상관 페널티
  leverage_ratio        × 0.15  — 평균 레버리지 / 시스템 최대 20x

레벨:
  [0.0, 0.30) → safe
  [0.30, 0.50) → moderate
  [0.50, 0.75) → elevated
  [0.75, 1.0]  → critical
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from agents.portfolio.calculator import check_concentration
from agents.portfolio.models import (
    CONCENTRATION_WARNING_PCT,
    MAX_SINGLE_COIN_PORTFOLIO_RATIO,
    PORTFOLIO_RISK_WARNING_PCT,
    SCORE_WEIGHT_CONCENTRATION,
    SCORE_WEIGHT_CORRELATION,
    SCORE_WEIGHT_LEVERAGE,
    SCORE_WEIGHT_PORTFOLIO_RISK,
    SYSTEM_MAX_LEVERAGE,
    _SCORE_LEVELS,
    AccountContext,
    CorrelationRisk,
    PortfolioRiskScore,
    PortfolioSnapshot,
    RiskScoreComponents,
)


def calculate_risk_score(
    snapshot: PortfolioSnapshot,
    corr_risk: CorrelationRisk,
    account: AccountContext,
    positions_leverage: Sequence[int],
) -> PortfolioRiskScore:
    """포트폴리오 종합 리스크 점수를 계산한다."""

    # 컴포넌트 1: 포트폴리오 총 리스크 비율 (§3.2)
    limit_usdt = account.max_risk_usdt
    portfolio_risk_ratio = (
        float(snapshot.total_risk_usdt / limit_usdt)
        if limit_usdt > 0 else 0.0
    )
    portfolio_risk_ratio = min(portfolio_risk_ratio, 1.0)

    # 컴포넌트 2: 집중도 비율 (§2.4)
    concentration_ratio = (
        snapshot.max_concentration_pct / MAX_SINGLE_COIN_PORTFOLIO_RATIO
        if MAX_SINGLE_COIN_PORTFOLIO_RATIO > 0 else 0.0
    )
    concentration_ratio = min(concentration_ratio, 1.0)

    # 컴포넌트 3: 동일 방향 BTC-ETH 상관 페널티
    correlation_penalty = _calc_correlation_penalty(corr_risk)

    # 컴포넌트 4: 평균 레버리지 비율
    avg_leverage = (
        sum(positions_leverage) / len(positions_leverage)
        if positions_leverage else 0.0
    )
    leverage_ratio = min(avg_leverage / SYSTEM_MAX_LEVERAGE, 1.0)

    components = RiskScoreComponents(
        portfolio_risk_ratio=round(portfolio_risk_ratio, 4),
        concentration_ratio=round(concentration_ratio, 4),
        correlation_penalty=round(correlation_penalty, 4),
        leverage_ratio=round(leverage_ratio, 4),
    )

    score = (
        SCORE_WEIGHT_PORTFOLIO_RISK * portfolio_risk_ratio
        + SCORE_WEIGHT_CONCENTRATION * concentration_ratio
        + SCORE_WEIGHT_CORRELATION * correlation_penalty
        + SCORE_WEIGHT_LEVERAGE * leverage_ratio
    )
    score = round(min(score, 1.0), 4)

    level = _score_to_level(score)
    breaches, warnings = _check_rules(snapshot, account)
    max_additional = _calc_max_additional_risk(snapshot, account)

    can_add = (
        not snapshot.is_emergency
        and len(breaches) == 0
        and max_additional > Decimal("0")
    )

    return PortfolioRiskScore(
        score=score,
        level=level,
        components=components,
        breaches=breaches,
        warnings=warnings,
        can_add_position=can_add,
        max_additional_risk_usdt=max_additional,
    )


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _calc_correlation_penalty(corr_risk: CorrelationRisk) -> float:
    """동일 방향 BTC-ETH 포지션에 대한 상관 페널티 (0.0~1.0).

    동일 방향(ρ > 0): rho를 페널티로 직접 사용.
    반대 방향 또는 단일 자산: 페널티 없음.
    """
    for _, dir_a, _, dir_b, rho in corr_risk.pairs:
        if dir_a == dir_b and rho > 0:
            return min(rho, 1.0)
    return 0.0


def _score_to_level(score: float) -> str:
    for threshold, level in _SCORE_LEVELS:
        if score < threshold:
            return level
    return "critical"


def _check_rules(
    snapshot: PortfolioSnapshot,
    account: AccountContext,
) -> tuple[list[str], list[str]]:
    """§2.4, §3.2, §10.4 규칙 위반(breaches)과 경고(warnings)."""
    breaches: list[str] = []
    warnings: list[str] = []

    # §3.2 포트폴리오 총 리스크
    limit_usdt = account.max_risk_usdt
    if limit_usdt > 0:
        ratio = float(snapshot.total_risk_usdt / limit_usdt)
        if ratio >= 1.0:
            breaches.append(
                f"PORTFOLIO_RISK: 총 리스크 ${float(snapshot.total_risk_usdt):.2f} "
                f">= 한도 ${float(limit_usdt):.2f} "
                f"({float(account.portfolio_risk_limit):.0%})"
            )
        elif ratio >= PORTFOLIO_RISK_WARNING_PCT:
            warnings.append(
                f"PORTFOLIO_RISK_WARNING: 총 리스크가 한도의 {ratio:.0%} 도달"
            )

    # §2.4 집중도 한도
    ok, reason = check_concentration(snapshot)
    if not ok:
        breaches.append(reason)
    else:
        conc_limit = MAX_SINGLE_COIN_PORTFOLIO_RATIO
        if (conc_limit > 0
                and snapshot.max_concentration_pct >= conc_limit * CONCENTRATION_WARNING_PCT):
            warnings.append(
                f"CONCENTRATION_WARNING: {snapshot.max_concentration_coin} "
                f"집중도 {snapshot.max_concentration_pct:.1%} "
                f"(한도 {conc_limit:.0%}의 {CONCENTRATION_WARNING_PCT:.0%} 도달)"
            )

    # §10.4 비상 잔고
    if snapshot.is_emergency:
        breaches.append(
            f"EMERGENCY: 잔고 ${float(snapshot.available_balance):.2f}가 "
            f"초기 잔고의 10% 미만 — 전체 청산 권고"
        )

    return breaches, warnings


def _calc_max_additional_risk(
    snapshot: PortfolioSnapshot,
    account: AccountContext,
) -> Decimal:
    """추가 가능한 최대 리스크 USDT (0 이상)."""
    remaining = account.max_risk_usdt - snapshot.total_risk_usdt
    return max(remaining, Decimal("0"))
