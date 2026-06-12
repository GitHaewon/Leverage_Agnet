"""
Derivatives market scoring — 선물 파생 데이터 리스크 필터.

규칙:
  - AI 호출 없음. 주문 없음. 순수 점수 함수.
  - 파생 데이터는 직접 거래 트리거가 아니라 방향 조정 및 혼잡도 필터로 작동한다.
  - 데이터 없음 → 안전한 중립 반환 (예외 없음).
  - 모든 출력 범위 클램프:
      long/short_score_adjustment: -30 ~ +30
      risk_score: 0 ~ 100
"""
from __future__ import annotations

from typing import Any

from agents.decision.models import (
    DerivativesMarketScore,
    MarketRegime,
    MarketRegimeResult,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _cfg(config: dict | None, key: str, default: Any) -> Any:
    return config.get(key, default) if config else default


def _as_regime(market_regime: Any) -> MarketRegime:
    if isinstance(market_regime, MarketRegimeResult):
        return market_regime.regime
    if isinstance(market_regime, MarketRegime):
        return market_regime
    if market_regime is None:
        return MarketRegime.UNKNOWN
    try:
        return MarketRegime(str(market_regime))
    except ValueError:
        return MarketRegime.UNKNOWN


def _read(data: Any, key: str, default: Any = None) -> Any:
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _has_any_derivatives_data(data: Any) -> bool:
    if data is None:
        return False
    keys = (
        "funding_rate",
        "open_interest",
        "open_interest_change",
        "open_interest_change_pct",
        "oi_change_pct",
        "long_short_ratio",
        "long_account_ratio",
        "short_account_ratio",
        "liquidation_volume",
        "liquidation_usdt",
        "liquidations",
    )
    return any(_read(data, key) is not None for key in keys)


def _extract_liquidation_notional(derivatives_data: Any) -> float:
    direct = _first_float(
        _read(derivatives_data, "liquidation_usdt"),
        _read(derivatives_data, "liquidation_volume"),
        _read(derivatives_data, "liquidations_usdt"),
    )
    if direct is not None:
        return direct

    liquidations = _read(derivatives_data, "liquidations")
    if not isinstance(liquidations, (list, tuple)):
        return 0.0

    total = 0.0
    for item in liquidations:
        total += _first_float(
            _read(item, "value_usdt"),
            _read(item, "notional"),
            _read(item, "amount"),
            0.0,
        ) or 0.0
    return total


def score_derivatives_market(
    derivatives_data: Any | None,
    price_data: Any | None,
    market_regime: Any | None,
    config: dict | None = None,
) -> DerivativesMarketScore:
    """
    선물 파생 시장 데이터를 점수화한다.

    Parameters
    ----------
    derivatives_data: funding_rate, open_interest_change, long_short_ratio 등 dict/duck type.
    price_data:       price_change, volume_change 등 dict/duck type.
    market_regime:    MarketRegime / MarketRegimeResult / None.
    config:           런타임 임계값 오버라이드 dict (선택).

    Returns
    -------
    DerivativesMarketScore
      long/short_score_adjustment, risk_score, crowded_side, reasons
    """
    if not _has_any_derivatives_data(derivatives_data):
        return DerivativesMarketScore.neutral()

    funding_rate = _first_float(_read(derivatives_data, "funding_rate")) or 0.0
    oi_change = _first_float(
        _read(derivatives_data, "open_interest_change"),
        _read(derivatives_data, "open_interest_change_pct"),
        _read(derivatives_data, "oi_change_pct"),
        _read(derivatives_data, "oi_1h_change_pct"),
    ) or 0.0
    long_short_ratio = _first_float(_read(derivatives_data, "long_short_ratio"))
    long_account_ratio = _first_float(
        _read(derivatives_data, "long_account_ratio"),
        _read(derivatives_data, "long_account_pct"),
    )
    short_account_ratio = _first_float(
        _read(derivatives_data, "short_account_ratio"),
        _read(derivatives_data, "short_account_pct"),
    )
    price_change = _first_float(
        _read(price_data, "price_change"),
        _read(price_data, "price_change_pct"),
        _read(price_data, "recent_price_change_pct"),
        _read(derivatives_data, "price_change"),
        _read(derivatives_data, "price_change_pct"),
    ) or 0.0
    volume_change = _first_float(
        _read(price_data, "volume_change"),
        _read(price_data, "volume_change_pct"),
        _read(derivatives_data, "volume_change"),
        _read(derivatives_data, "volume_change_pct"),
    ) or 0.0
    liquidation_notional = _extract_liquidation_notional(derivatives_data)
    regime = _as_regime(market_regime)

    high_funding = float(_cfg(config, "high_funding_rate", 0.0010))
    strong_negative_funding = float(_cfg(config, "strong_negative_funding_rate", -0.0010))
    neutral_funding_abs = float(_cfg(config, "neutral_funding_abs", 0.0003))
    oi_up_pct = float(_cfg(config, "oi_up_pct", 0.5))
    oi_drop_pct = float(_cfg(config, "oi_drop_pct", -2.0))
    price_move_pct = float(_cfg(config, "price_move_pct", 0.25))
    price_spike_pct = float(_cfg(config, "price_spike_pct", 2.0))
    long_crowd_ratio = float(_cfg(config, "long_crowd_ratio", 1.5))
    short_crowd_ratio = float(_cfg(config, "short_crowd_ratio", 0.67))
    account_crowd_pct = float(_cfg(config, "account_crowd_pct", 60.0))
    liquidation_risk_usdt = float(_cfg(config, "liquidation_risk_usdt", 1_000_000.0))
    max_adj = float(_cfg(config, "max_score_adjustment", 30.0))

    long_adj = 0.0
    short_adj = 0.0
    risk_score = 0.0
    crowded_side: str = "NONE"
    reasons: list[str] = []

    long_account_pct = (
        long_account_ratio * 100.0
        if long_account_ratio is not None and long_account_ratio <= 1.0
        else long_account_ratio
    )
    short_account_pct = (
        short_account_ratio * 100.0
        if short_account_ratio is not None and short_account_ratio <= 1.0
        else short_account_ratio
    )

    long_crowded = (
        (long_short_ratio is not None and long_short_ratio >= long_crowd_ratio)
        or (long_account_pct is not None and long_account_pct >= account_crowd_pct)
    )
    short_crowded = (
        (long_short_ratio is not None and long_short_ratio <= short_crowd_ratio)
        or (short_account_pct is not None and short_account_pct >= account_crowd_pct)
    )

    if long_crowded:
        crowded_side = "LONG"
        risk_score += 18.0
        reasons.append("롱 포지션 쏠림 감지 — crowded_side=LONG")
    elif short_crowded:
        crowded_side = "SHORT"
        risk_score += 18.0
        reasons.append("숏 포지션 쏠림 감지 — crowded_side=SHORT")

    # Price up + OI up + neutral funding: 신규 롱 참여로 해석하되 소폭만 반영.
    if (
        price_change > price_move_pct
        and oi_change > oi_up_pct
        and abs(funding_rate) <= neutral_funding_abs
    ):
        long_adj += 8.0
        risk_score += 5.0
        reasons.append(
            f"가격 {price_change:+.2f}% + OI {oi_change:+.2f}% + 중립 펀딩 → 롱 소폭 우대"
        )

    # High funding + long crowding: 롱 추격 감점.
    if (
        price_change > price_move_pct
        and oi_change > oi_up_pct
        and funding_rate >= high_funding
        and long_crowded
    ):
        long_adj -= 14.0
        short_adj += 4.0
        risk_score += 28.0
        crowded_side = "LONG"
        reasons.append(
            f"고펀딩 {funding_rate:.4%} + 롱 쏠림 + OI 증가 — 롱 추격 감점"
        )
    elif funding_rate >= high_funding:
        long_adj -= 6.0
        risk_score += 15.0
        reasons.append(f"고펀딩 {funding_rate:.4%} — LONG 추격 경고")

    # Negative funding + short crowding: 숏 추격 감점.
    if (
        price_change < -price_move_pct
        and oi_change > oi_up_pct
        and funding_rate <= strong_negative_funding
        and short_crowded
    ):
        short_adj -= 14.0
        long_adj += 4.0
        risk_score += 28.0
        crowded_side = "SHORT"
        reasons.append(
            f"강한 음수 펀딩 {funding_rate:.4%} + 숏 쏠림 + OI 증가 — 숏 추격 감점"
        )
    elif funding_rate <= strong_negative_funding:
        short_adj -= 6.0
        risk_score += 15.0
        reasons.append(f"강한 음수 펀딩 {funding_rate:.4%} — SHORT 추격 경고")

    # Price spike + OI drop: 레버리지 포지션 청산 가능성.
    if abs(price_change) >= price_spike_pct and oi_change <= oi_drop_pct:
        risk_score += 25.0
        if price_change > 0:
            short_adj -= 4.0
        else:
            long_adj -= 4.0
        reasons.append(
            f"가격 급변 {price_change:+.2f}% + OI 감소 {oi_change:+.2f}% — 청산 이벤트 가능성"
        )

    if liquidation_notional >= liquidation_risk_usdt:
        risk_score += 20.0
        reasons.append(
            f"대규모 청산 데이터 감지 (${liquidation_notional:,.0f}) — 리스크 증가"
        )

    if abs(volume_change) >= 50.0 and abs(price_change) >= price_move_pct:
        risk_score += 6.0
        reasons.append(f"거래량 변화 {volume_change:+.1f}% 동반 — 파생 리스크 소폭 증가")

    if regime == MarketRegime.HIGH_VOLATILITY:
        risk_score += 20.0
        reasons.append("HIGH_VOLATILITY 국면 — 파생 리스크 증가")
    elif regime == MarketRegime.NEWS_EVENT:
        risk_score += 25.0
        reasons.append("NEWS_EVENT 국면 — 파생 리스크 증가")
    elif regime == MarketRegime.UNKNOWN:
        risk_score += 5.0
        reasons.append("UNKNOWN 국면 — 파생 데이터 보수적 처리")

    if not reasons:
        reasons.append("파생 시장 특이 신호 없음 — 중립")

    return DerivativesMarketScore(
        long_score_adjustment=round(_clamp(long_adj, -max_adj, max_adj), 2),
        short_score_adjustment=round(_clamp(short_adj, -max_adj, max_adj), 2),
        risk_score=round(_clamp(risk_score, 0.0, 100.0), 2),
        crowded_side=crowded_side,  # type: ignore[arg-type]
        reasons=reasons,
    )
