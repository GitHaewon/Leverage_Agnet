"""
Position Sizing Engine — 4가지 사이징 방법 통합.

모든 방법의 공통 원칙:
  1. 리스크 금액 계산 (방법별)
  2. 안전 상한 적용 (max/min risk_pct)
  3. 포지션 크기 공식 적용 (sl_distance 기반)
  4. lot_size 반올림 + 유효성 검증

계층:
  PositionSizingEngine (API)
    └── _FixedRiskSizer     — balance × pct
    └── _FixedDollarSizer   — 고정 USDT
    └── _PercentRiskSizer   — available_balance × pct
    └── _KellySizer         — Kelly fraction → FixedRisk
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Protocol

from agents.risk.constants import (
    BINANCE_LOT_SIZES,
    BINANCE_MIN_NOTIONAL,
    MARGIN_BUFFER_RATIO,
    MAX_SINGLE_POSITION_MARGIN_RATIO,
    PLAN_MAX_LEVERAGE,
    RISK_PER_TRADE_MAX,
    RISK_PER_TRADE_MIN,
    SYSTEM_MAX_LEVERAGE,
)
from agents.risk.kelly import calculate_kelly, recommended_kelly_fraction
from agents.risk.models import AccountState, RawSignal
from agents.risk.sizing import validate_rr_ratio, round_to_lot_size
from agents.risk.sizing_models import (
    KellyResult,
    SizingComparison,
    SizingConfig,
    SizingMethod,
    SizingResult,
    TradeStatistics,
)

logger = logging.getLogger(__name__)

_PRECISION = Decimal("0.0001")


# ════════════════════════════════════════════════════════════════
# 내부 Sizer 프로토콜
# ════════════════════════════════════════════════════════════════

class _SizerProtocol(Protocol):
    def get_risk_amount(
        self,
        config: SizingConfig,
        account: AccountState,
        trade_stats: TradeStatistics | None,
    ) -> tuple[Decimal, KellyResult | None, list[str]]:
        """
        Returns: (risk_amount_usdt, kelly_result_or_None, warnings)
        """
        ...


# ════════════════════════════════════════════════════════════════
# 4가지 사이징 방법 구현
# ════════════════════════════════════════════════════════════════

class _FixedRiskSizer:
    """
    Fixed Risk — 총 잔고의 N%를 손실 한도로 설정.
    TRADING_RULES.md §7.1 표준 방법.
    """

    def get_risk_amount(
        self,
        config: SizingConfig,
        account: AccountState,
        trade_stats: TradeStatistics | None,
    ) -> tuple[Decimal, None, list[str]]:
        pct = config.risk_pct if config.risk_pct is not None else RISK_PER_TRADE_MIN
        pct = _clamp_risk_pct(pct, config)
        risk = account.total_balance * Decimal(str(pct))
        return risk, None, []


class _FixedDollarSizer:
    """
    Fixed Dollar — 거래당 고정 USDT 금액을 손실 한도로 설정.
    계좌 크기와 무관하게 절대 금액으로 리스크 제어.
    """

    def get_risk_amount(
        self,
        config: SizingConfig,
        account: AccountState,
        trade_stats: TradeStatistics | None,
    ) -> tuple[Decimal, None, list[str]]:
        warnings: list[str] = []

        if config.risk_usdt is None or config.risk_usdt <= 0:
            # fallback: 1% of balance
            risk = account.total_balance * Decimal("0.01")
            warnings.append("FIXED_DOLLAR: risk_usdt 미설정 — 잔고의 1% 적용")
        else:
            risk = config.risk_usdt

        # USDT 금액도 안전 상한(%)으로 클리핑
        max_risk = account.total_balance * Decimal(str(config.max_risk_pct))
        min_risk = account.total_balance * Decimal(str(config.min_risk_pct))

        if risk > max_risk:
            warnings.append(
                f"FIXED_DOLLAR: ${risk:.2f} → 상한 ${max_risk:.2f} 적용 ({config.max_risk_pct:.1%})"
            )
            risk = max_risk
        if risk < min_risk:
            warnings.append(
                f"FIXED_DOLLAR: ${risk:.2f} → 하한 ${min_risk:.2f} 적용 ({config.min_risk_pct:.1%})"
            )
            risk = min_risk

        return risk, None, warnings


class _PercentRiskSizer:
    """
    Percent Risk — 가용 잔고(Available Balance)의 N%.
    Fixed Risk와 다른 점: 총 잔고가 아닌 실제 사용 가능 잔고 기준.
    증거금이 잠긴 상태에서 남은 자본을 더 정확히 반영.
    """

    def get_risk_amount(
        self,
        config: SizingConfig,
        account: AccountState,
        trade_stats: TradeStatistics | None,
    ) -> tuple[Decimal, None, list[str]]:
        pct = config.risk_pct if config.risk_pct is not None else RISK_PER_TRADE_MIN
        pct = _clamp_risk_pct(pct, config)
        risk = account.available_balance * Decimal(str(pct))
        return risk, None, []


class _KellySizer:
    """
    Kelly Criterion — 수학적 최적 베팅 비율.

    장점: 장기적 자본 성장 최대화
    단점: 단기 변동성 높음, 충분한 데이터 필요

    실전: Quarter-Kelly (0.25×) 기본 적용으로 변동성 완화.
    """

    def get_risk_amount(
        self,
        config: SizingConfig,
        account: AccountState,
        trade_stats: TradeStatistics | None,
    ) -> tuple[Decimal, KellyResult, list[str]]:
        warnings: list[str] = []

        if trade_stats is None or not trade_stats.is_sufficient:
            # 거래 이력 없음 → fallback
            fallback = Decimal(str(config.kelly_fallback_risk_pct))
            risk = account.total_balance * fallback
            warnings.append(
                f"KELLY: 거래 이력 없음 — fallback {config.kelly_fallback_risk_pct:.1%} 적용"
            )
            kelly_result = KellyResult(
                full_kelly_fraction=float(fallback),
                applied_fraction=float(fallback),
                kelly_multiplier=config.kelly_fraction,
                win_rate=0.0,
                avg_odds=0.0,
                sample_size=0,
                is_valid=False,
                reason="거래 이력 없음",
            )
            return risk, kelly_result, warnings

        # 샘플 크기 기반 자동 분수 선택 (override 없으면)
        auto_fraction = recommended_kelly_fraction(
            trade_stats.total_trades,
            trade_stats.win_rate,
            trade_stats.avg_odds,
        )
        effective_fraction = max(auto_fraction, config.kelly_fraction)

        kelly_result = calculate_kelly(
            stats=trade_stats,
            kelly_fraction=effective_fraction,
            min_sample_size=config.kelly_min_trades,
            fallback_risk_pct=config.kelly_fallback_risk_pct,
        )

        if not kelly_result.is_valid:
            warnings.append(
                f"KELLY: 유효하지 않음 ({kelly_result.reason}) — fallback 적용"
            )

        risk_pct = kelly_result.capped_risk_pct
        risk = account.total_balance * Decimal(str(risk_pct))

        if kelly_result.full_kelly_fraction > config.max_risk_pct:
            warnings.append(
                f"KELLY: Full Kelly {kelly_result.full_kelly_fraction:.1%} → "
                f"상한 {config.max_risk_pct:.1%} 클리핑"
            )

        logger.info(
            "Kelly applied: win_rate=%.1f%% odds=%.3f full=%.1f%% "
            "fraction=%.2f final=%.1f%%",
            kelly_result.win_rate * 100,
            kelly_result.avg_odds,
            kelly_result.full_kelly_fraction * 100,
            effective_fraction,
            risk_pct * 100,
        )

        return risk, kelly_result, warnings


# ════════════════════════════════════════════════════════════════
# 메인 Position Sizing Engine
# ════════════════════════════════════════════════════════════════

_SIZERS: dict[SizingMethod, _SizerProtocol] = {
    SizingMethod.FIXED_RISK:   _FixedRiskSizer(),
    SizingMethod.FIXED_DOLLAR: _FixedDollarSizer(),
    SizingMethod.PERCENT_RISK: _PercentRiskSizer(),
    SizingMethod.KELLY:        _KellySizer(),
}


class PositionSizingEngine:
    """
    4가지 포지션 사이징 방법 통합 엔진.

    사용 예:
        engine = PositionSizingEngine()
        result = engine.calculate(config, signal, account, leverage, symbol)
        comparison = engine.compare_all(signal, account, leverage, symbol, stats)
    """

    # ── 단일 방법 계산 ────────────────────────────────────────────────────────

    def calculate(
        self,
        config: SizingConfig,
        signal: RawSignal,
        account: AccountState,
        leverage: int,
        symbol: str,
        trade_stats: TradeStatistics | None = None,
    ) -> SizingResult:
        """
        지정된 방법으로 포지션 사이징 계산.
        stop_loss 없으면 ValueError 발생 (절대 규칙).
        """
        if signal.stop_loss is None or signal.stop_loss <= 0:
            raise ValueError("stop_loss가 없거나 0 이하입니다 — SL 없는 주문 절대 금지")

        sizer = _SIZERS[config.method]
        risk_amount, kelly_result, warnings = sizer.get_risk_amount(
            config, account, trade_stats
        )

        return _build_sizing_result(
            method=config.method,
            risk_amount=risk_amount,
            signal=signal,
            account=account,
            leverage=leverage,
            symbol=symbol,
            kelly_result=kelly_result,
            warnings=warnings,
        )

    # ── 4가지 방법 비교 ───────────────────────────────────────────────────────

    def compare_all(
        self,
        signal: RawSignal,
        account: AccountState,
        leverage: int,
        symbol: str,
        base_risk_pct: float = 0.02,
        base_risk_usdt: Decimal | None = None,
        kelly_fraction: float = 0.25,
        trade_stats: TradeStatistics | None = None,
    ) -> SizingComparison:
        """
        4가지 방법을 동일 조건으로 계산해 비교 테이블 반환.
        포지션 개설 전 방법 선택에 활용.
        """
        results: dict[str, dict] = {}

        configs: list[tuple[SizingMethod, SizingConfig]] = [
            (
                SizingMethod.FIXED_RISK,
                SizingConfig(method=SizingMethod.FIXED_RISK, risk_pct=base_risk_pct),
            ),
            (
                SizingMethod.FIXED_DOLLAR,
                SizingConfig(
                    method=SizingMethod.FIXED_DOLLAR,
                    risk_usdt=base_risk_usdt or (account.total_balance * Decimal(str(base_risk_pct))),
                ),
            ),
            (
                SizingMethod.PERCENT_RISK,
                SizingConfig(method=SizingMethod.PERCENT_RISK, risk_pct=base_risk_pct),
            ),
            (
                SizingMethod.KELLY,
                SizingConfig(method=SizingMethod.KELLY, kelly_fraction=kelly_fraction),
            ),
        ]

        for method, config in configs:
            try:
                result = self.calculate(config, signal, account, leverage, symbol, trade_stats)
                results[method.value] = result.to_dict()
            except Exception as exc:
                results[method.value] = {
                    "method": method.value,
                    "error": str(exc),
                    "quantity": "0",
                }

        return SizingComparison(
            signal_symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,  # type: ignore[arg-type]
            take_profit=signal.take_profit,
            leverage=leverage,
            account_balance=account.total_balance,
            results=results,
        )

    # ── 사이징 유효성 검증 ────────────────────────────────────────────────────

    def validate(
        self,
        result: SizingResult,
        available_balance: Decimal,
        entry_price: Decimal,
        symbol: str,
    ) -> tuple[bool, str]:
        """SizingResult가 거래 가능한지 최종 검증."""
        from agents.risk.sizing import validate_position_size
        from agents.risk.models import PositionSizingResult

        # PositionSizingResult로 변환해 기존 검증 함수 재사용
        base = PositionSizingResult(
            quantity=result.quantity,
            margin_used=result.margin_used,
            position_value=result.position_value,
            max_loss=result.max_loss,
            max_profit=result.max_profit,
            final_leverage=result.final_leverage,
        )
        return validate_position_size(base, available_balance, entry_price, symbol)


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 함수
# ════════════════════════════════════════════════════════════════

def _clamp_risk_pct(pct: float, config: SizingConfig) -> float:
    return max(config.min_risk_pct, min(config.max_risk_pct, pct))


def _build_sizing_result(
    method: SizingMethod,
    risk_amount: Decimal,
    signal: RawSignal,
    account: AccountState,
    leverage: int,
    symbol: str,
    kelly_result: KellyResult | None,
    warnings: list[str],
) -> SizingResult:
    """
    리스크 금액 → 포지션 크기 공식 적용 → SizingResult 생성.

    공식 (TRADING_RULES.md §7.1):
      sl_distance   = |entry - stop_loss|
      position_size = risk_amount / sl_distance  (증거금 USDT)
      quantity      = (position_size × leverage) / entry_price
    """
    entry = signal.entry_price
    sl = signal.stop_loss  # type: ignore[assignment]
    tp = signal.take_profit

    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        raise ValueError("entry와 stop_loss가 동일합니다")

    # 포지션 크기 계산
    margin_used = risk_amount / sl_distance
    raw_qty = (margin_used * leverage) / entry
    quantity = round_to_lot_size(raw_qty, symbol)
    position_value = margin_used * leverage

    # R:R 계산
    rr = Decimal("0")
    max_profit = Decimal("0")
    if tp is not None:
        ok, rr, _ = validate_rr_ratio(entry, tp, sl, signal.direction)
        if ok and rr > 0:
            max_profit = risk_amount * rr

    # 실제 적용된 리스크 비율
    actual_risk_pct = (
        float(risk_amount / account.total_balance)
        if account.total_balance > 0 else 0.0
    )

    # 레버리지 경고
    plan_max = PLAN_MAX_LEVERAGE.get("pro", 10)  # 기본 Pro 기준
    if leverage > plan_max:
        warnings.append(f"LEVERAGE: {leverage}x → 플랜 최대 {plan_max}x 초과")

    # 잔고 부족 경고
    required = margin_used * Decimal(str(MARGIN_BUFFER_RATIO))
    if required > account.available_balance:
        warnings.append(
            f"BALANCE: 필요 증거금 ${required:.2f} > 가용 잔고 ${account.available_balance:.2f}"
        )

    logger.debug(
        "Sizing[%s]: risk=$%.2f sl_dist=$%.4f margin=$%.2f qty=%s lev=%dx",
        method.value, risk_amount, sl_distance, margin_used, quantity, leverage,
    )

    return SizingResult(
        method=method,
        risk_amount_usdt=risk_amount.quantize(Decimal("0.01")),
        risk_pct=actual_risk_pct,
        quantity=quantity,
        margin_used=margin_used.quantize(Decimal("0.01")),
        position_value=position_value.quantize(Decimal("0.01")),
        max_loss=risk_amount.quantize(Decimal("0.01")),
        max_profit=max_profit.quantize(Decimal("0.01")),
        final_leverage=leverage,
        rr_ratio=rr.quantize(Decimal("0.01")) if rr else Decimal("0"),
        kelly=kelly_result,
        warnings=warnings,
    )
