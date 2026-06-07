"""
PortfolioEngine — 포트폴리오 관리 단일 진입점.

모든 포트폴리오 연산은 이 클래스를 통해 수행한다.
DB 저장, WebSocket 이벤트, Binance API 호출은 호출자(서비스 레이어) 책임이다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from agents.portfolio.calculator import (
    build_snapshot,
    check_concentration,
    check_single_position_margin,
)
from agents.portfolio.correlation import calculate_correlation_risk
from agents.portfolio.models import (
    BTC_ETH_CORRELATION,
    AccountContext,
    CorrelationRisk,
    PortfolioPosition,
    PortfolioRiskScore,
    PortfolioSnapshot,
)
from agents.portfolio.scorer import calculate_risk_score


class PortfolioEngine:
    """포트폴리오 생명주기 오케스트레이터.

    모든 메서드는 순수 도메인 연산 — 외부 I/O 없음.
    """

    def __init__(self, btc_eth_correlation: float = BTC_ETH_CORRELATION) -> None:
        self._corr = btc_eth_correlation

    # ── 스냅샷 ────────────────────────────────────────────────────────────────

    def snapshot(
        self,
        positions: Sequence[PortfolioPosition],
        account: AccountContext,
    ) -> PortfolioSnapshot:
        """전체 계좌 관리 + 총/심볼별 노출도 스냅샷."""
        return build_snapshot(positions, account)

    # ── 상관관계 ─────────────────────────────────────────────────────────────

    def correlation_risk(
        self,
        positions: Sequence[PortfolioPosition],
    ) -> CorrelationRisk:
        """BTC-ETH 상관관계 기반 위험 계산."""
        return calculate_correlation_risk(positions, self._corr)

    # ── 리스크 점수 ───────────────────────────────────────────────────────────

    def risk_score(
        self,
        positions: Sequence[PortfolioPosition],
        account: AccountContext,
    ) -> PortfolioRiskScore:
        """포트폴리오 종합 리스크 점수 (0.0~1.0)."""
        snap = build_snapshot(positions, account)
        corr = calculate_correlation_risk(positions, self._corr)
        leverages = [p.leverage for p in positions]
        return calculate_risk_score(snap, corr, account, leverages)

    # ── 포지션 추가 가능 여부 ─────────────────────────────────────────────────

    def can_add_position(
        self,
        positions: Sequence[PortfolioPosition],
        account: AccountContext,
        new_risk_usdt: Decimal,
    ) -> tuple[bool, str]:
        """§3.2 포트폴리오 리스크 한도 및 §10.4 비상 상태 체크.

        Returns: (can_add: bool, reason: str)
        """
        snap = build_snapshot(positions, account)

        if snap.is_emergency:
            return False, (
                "EMERGENCY: 잔고가 초기 잔고의 10% 미만 — 신규 포지션 불가"
            )

        projected = snap.total_risk_usdt + new_risk_usdt
        limit = account.max_risk_usdt
        if projected > limit:
            return False, (
                f"PORTFOLIO_RISK: 포트폴리오 총 위험 ${float(projected):.2f}가 "
                f"한도 ${float(limit):.2f} "
                f"({float(account.portfolio_risk_limit):.0%}) 초과"
            )

        return True, "OK"

    # ── 집중도 / 증거금 체크 ─────────────────────────────────────────────────

    def check_concentration(
        self,
        positions: Sequence[PortfolioPosition],
        account: AccountContext,
    ) -> tuple[bool, str]:
        """§2.4 단일 코인 집중도 50% 한도 체크."""
        snap = build_snapshot(positions, account)
        return check_concentration(snap)

    def check_margin(
        self,
        position: PortfolioPosition,
        account: AccountContext,
    ) -> tuple[bool, str]:
        """§3.3 단일 포지션 증거금 20% 한도 체크."""
        return check_single_position_margin(position, account)
