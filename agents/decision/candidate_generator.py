"""
Trade candidate generator — 결정적 TradeCandidate 생성.

규칙:
  - AI 호출 없음. 주문 없음. 순수 후보 생성 함수.
  - RiskEngine / Execution / Synthesis 를 호출하거나 우회하지 않는다.
  - LONG/SHORT 후보는 항상 stop_loss 와 take_profit 을 가진다.
  - HOLD 후보는 실행 불가 상태를 안전한 0 값으로 표현한다.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from agents.decision.constants import (
    DECISION_MAX_ENTRY_MARGIN_RATIO,
    DECISION_MAX_LEVERAGE,
    DEFAULT_SLIPPAGE_BPS,
    GLOBAL_MIN_RISK_REWARD_RATIO,
    MAX_RISK_SCORE,
    MIN_LONG_SCORE,
    MIN_SHORT_SCORE,
    TAKER_FEE_RATE,
)
from agents.decision.models import (
    FinalAction,
    MarketRegime,
    MarketRegimeResult,
    StrategySelectionResult,
    StrategyType,
    TradeCandidate,
)


_DECIMAL_ZERO = Decimal("0")
_PRICE_Q = Decimal("0.01")
_MONEY_Q = Decimal("0.0001")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def _first_decimal(*values: Any) -> Decimal | None:
    for value in values:
        if value is None:
            continue
        try:
            dec = Decimal(str(value))
        except Exception:
            continue
        if dec > 0:
            return dec
    return None


def _cfg(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default

    decision = _read(config, "decision")
    if decision is not None:
        value = _read(decision, key)
        if value is not None:
            return value

    value = _read(config, key)
    return default if value is None else value


def _as_strategy_type(value: Any) -> StrategyType:
    if isinstance(value, StrategySelectionResult):
        return value.strategy_type
    if isinstance(value, StrategyType):
        return value
    try:
        return StrategyType(str(value))
    except ValueError:
        return StrategyType.UNKNOWN


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


def _q(value: Decimal, quantum: Decimal = _MONEY_Q) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _get_price(market_snapshot: Any, technical_result: Any, strategy_signal: Any) -> Decimal | None:
    primary = _select_primary_tf(technical_result)
    return _first_decimal(
        _read(market_snapshot, "current_price"),
        _read(market_snapshot, "price"),
        _read(market_snapshot, "mark_price"),
        _read(strategy_signal, "entry_price"),
        _read(strategy_signal, "entry"),
        _read(technical_result, "latest_close"),
        _read(primary, "close"),
    )


def _select_primary_tf(technical_result: Any) -> Any | None:
    analyses = _read(technical_result, "analyses", {}) or {}
    if not analyses:
        return None
    for timeframe in ("1h", "4h", "15m", "5m", "1d"):
        if timeframe in analyses:
            return analyses[timeframe]
    try:
        return next(iter(analyses.values()))
    except StopIteration:
        return None


def _extract_atr(technical_result: Any, entry: Decimal, config: Any) -> Decimal:
    primary = _select_primary_tf(technical_result)
    atr = _first_decimal(
        _read(primary, "atr"),
        _read(technical_result, "atr"),
        _read(config, "atr"),
    )
    if atr is not None:
        return atr
    fallback_pct = Decimal(str(_cfg(config, "default_stop_pct", 0.01)))
    return max(entry * fallback_pct, Decimal("0.01"))


def _levels(technical_result: Any, key: str) -> list[Decimal]:
    raw = _read(technical_result, key, []) or []
    levels: list[Decimal] = []
    for value in raw:
        level = _first_decimal(value)
        if level is not None:
            levels.append(level)
    return levels


def _nearest_below(levels: list[Decimal], price: Decimal) -> Decimal | None:
    below = [level for level in levels if level < price]
    return max(below) if below else None


def _nearest_above(levels: list[Decimal], price: Decimal) -> Decimal | None:
    above = [level for level in levels if level > price]
    return min(above) if above else None


def _combined_risk(chart_score: Any, news_score: Any, derivatives_score: Any) -> float:
    chart_risk = _first_float(_read(chart_score, "risk_score")) or 50.0
    news_risk = _first_float(_read(news_score, "risk_score")) or 0.0
    deriv_risk = _first_float(_read(derivatives_score, "risk_score")) or 0.0
    raw = chart_risk * 0.4 + news_risk * 0.3 + deriv_risk * 0.3
    return round(_clamp(raw, 0.0, 100.0), 2)


def _adjusted_scores(chart_score: Any, derivatives_score: Any) -> tuple[float, float]:
    long_score = _first_float(_read(chart_score, "long_score")) or 0.0
    short_score = _first_float(_read(chart_score, "short_score")) or 0.0
    long_adj = _first_float(_read(derivatives_score, "long_score_adjustment")) or 0.0
    short_adj = _first_float(_read(derivatives_score, "short_score_adjustment")) or 0.0
    return (
        round(_clamp(long_score + long_adj, 0.0, 100.0), 2),
        round(_clamp(short_score + short_adj, 0.0, 100.0), 2),
    )


def _make_hold(
    coin: str,
    symbol: str,
    strategy_type: StrategyType,
    expected_holding_minutes: int,
    min_required_rr: float,
    entry_price: Decimal | None,
    spread_bps: float,
    slippage_bps: float,
    reasons: list[str],
) -> TradeCandidate:
    return TradeCandidate(
        action=FinalAction.HOLD,
        coin=coin,
        symbol=symbol,
        strategy_type=strategy_type,
        expected_holding_minutes=expected_holding_minutes,
        entry_price=_q(entry_price or _DECIMAL_ZERO, _PRICE_Q),
        stop_loss=None,
        take_profit=None,
        leverage=0,
        margin_ratio=0.0,
        notional_size=_DECIMAL_ZERO,
        actual_rr=0.0,
        min_required_rr=min_required_rr,
        expected_gross_profit=None,
        expected_gross_loss=None,
        expected_fees=_DECIMAL_ZERO,
        expected_slippage_cost=_DECIMAL_ZERO,
        expected_net_profit=None,
        expected_net_loss=None,
        liquidation_price=None,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        reasons=reasons,
    )


def _compute_exits(
    action: FinalAction,
    entry: Decimal,
    technical_result: Any,
    strategy_signal: Any,
    min_required_rr: float,
    config: Any,
) -> tuple[Decimal | None, Decimal | None]:
    atr = _extract_atr(technical_result, entry, config)
    atr_mult = Decimal(str(_cfg(config, "stop_atr_multiplier", 1.5)))
    stop_distance = max(atr * atr_mult, entry * Decimal(str(_cfg(config, "min_stop_pct", 0.003))))
    min_rr = Decimal(str(max(min_required_rr, GLOBAL_MIN_RISK_REWARD_RATIO)))

    raw_sl = _first_decimal(_read(strategy_signal, "stop_loss"), _read(strategy_signal, "sl"))
    raw_tp = _first_decimal(_read(strategy_signal, "take_profit"), _read(strategy_signal, "tp"))

    supports = _levels(technical_result, "support_levels")
    resistances = _levels(technical_result, "resistance_levels")

    if action == FinalAction.LONG:
        stop_loss = raw_sl if raw_sl is not None and raw_sl < entry else None
        if stop_loss is None:
            support = _nearest_below(supports, entry)
            stop_loss = support if support is not None else entry - stop_distance
        if stop_loss >= entry:
            return None, None

        risk_distance = entry - stop_loss
        min_take_profit = entry + risk_distance * min_rr
        take_profit = raw_tp if raw_tp is not None and raw_tp > entry else None
        resistance = _nearest_above(resistances, entry)
        if take_profit is None and resistance is not None and resistance >= min_take_profit:
            take_profit = resistance
        if take_profit is None or take_profit < min_take_profit:
            take_profit = min_take_profit
        return _q(stop_loss, _PRICE_Q), _q(take_profit, _PRICE_Q)

    stop_loss = raw_sl if raw_sl is not None and raw_sl > entry else None
    if stop_loss is None:
        resistance = _nearest_above(resistances, entry)
        stop_loss = resistance if resistance is not None else entry + stop_distance
    if stop_loss <= entry:
        return None, None

    risk_distance = stop_loss - entry
    min_take_profit = entry - risk_distance * min_rr
    take_profit = raw_tp if raw_tp is not None and raw_tp < entry else None
    support = _nearest_below(supports, entry)
    if take_profit is None and support is not None and support <= min_take_profit:
        take_profit = support
    if take_profit is None or take_profit > min_take_profit:
        take_profit = min_take_profit
    if take_profit <= 0:
        return None, None
    return _q(stop_loss, _PRICE_Q), _q(take_profit, _PRICE_Q)


def _liquidation_price(action: FinalAction, entry: Decimal, leverage: int) -> Decimal | None:
    if leverage <= 0:
        return None
    lev = Decimal(str(leverage))
    if action == FinalAction.LONG:
        return _q(entry * (Decimal("1") - Decimal("1") / lev), _PRICE_Q)
    if action == FinalAction.SHORT:
        return _q(entry * (Decimal("1") + Decimal("1") / lev), _PRICE_Q)
    return None


def generate_trade_candidate(
    coin: str,
    symbol: str,
    market_snapshot: Any | None,
    technical_result: Any | None,
    strategy_signal: Any | None,
    market_regime: Any | None,
    chart_score: Any | None,
    news_score: Any | None,
    derivatives_score: Any | None,
    strategy_selection: StrategySelectionResult | Any | None,
    account_state: Any | None,
    config: Any | None = None,
) -> TradeCandidate:
    """
    결정적 점수와 시장 데이터로 실행 후보를 생성한다.

    LONG/SHORT 방향 결정은 chart_score 에 derivatives_score 의 조정치를 더한 값만
    사용한다.
    news_score 는 no_trade_flag 와 리스크에만 반영한다.
    """
    strategy_type = _as_strategy_type(_read(strategy_selection, "strategy_type"))
    expected_minutes = int(_read(strategy_selection, "expected_holding_minutes", 0) or 0)
    min_required_rr = float(_read(strategy_selection, "min_required_rr", 0.0) or 0.0)
    if min_required_rr <= 0 and strategy_type != StrategyType.UNKNOWN:
        min_required_rr = GLOBAL_MIN_RISK_REWARD_RATIO

    spread_bps = float(_cfg(config, "spread_bps", _read(market_snapshot, "spread_bps", 0.0)) or 0.0)
    slippage_bps = float(_cfg(config, "slippage_bps", DEFAULT_SLIPPAGE_BPS))
    entry = _get_price(market_snapshot, technical_result, strategy_signal)
    reasons: list[str] = []

    regime = _as_regime(market_regime)
    combined_risk = _combined_risk(chart_score, news_score, derivatives_score)
    max_risk = float(_cfg(config, "max_risk_score", MAX_RISK_SCORE))
    min_long = float(_cfg(config, "min_long_score", MIN_LONG_SCORE))
    min_short = float(_cfg(config, "min_short_score", MIN_SHORT_SCORE))
    long_score, short_score = _adjusted_scores(chart_score, derivatives_score)

    reasons.append(
        f"국면={regime.value}, 조정 롱점수={long_score:.1f}, "
        f"조정 숏점수={short_score:.1f}, 통합리스크={combined_risk:.1f}"
    )

    if strategy_type == StrategyType.UNKNOWN:
        reasons.append("strategy_type=UNKNOWN — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    if bool(_read(news_score, "no_trade_flag", False)):
        reasons.append("news_score.no_trade_flag=True — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    if combined_risk > max_risk:
        reasons.append(f"통합 리스크 {combined_risk:.1f} > 허용 {max_risk:.1f} — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    if entry is None or entry <= 0:
        reasons.append("필수 가격 데이터 없음 — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    long_strong = long_score >= min_long
    short_strong = short_score >= min_short
    if long_strong and short_strong:
        reasons.append("LONG/SHORT 점수가 모두 강함 — 충돌로 HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    if long_strong:
        action = FinalAction.LONG
        reasons.append(f"롱 점수 {long_score:.1f} >= 임계값 {min_long:.1f} — LONG 후보")
    elif short_strong:
        action = FinalAction.SHORT
        reasons.append(
            f"숏 점수 {short_score:.1f} >= 임계값 {min_short:.1f} — SHORT 후보"
        )
    else:
        reasons.append("LONG/SHORT 점수가 임계값 미만 — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    stop_loss, take_profit = _compute_exits(
        action,
        entry,
        technical_result,
        strategy_signal,
        min_required_rr,
        config,
    )
    if stop_loss is None or take_profit is None:
        reasons.append("stop_loss/take_profit 계산 실패 — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    if action == FinalAction.LONG:
        profit_distance = take_profit - entry
        loss_distance = entry - stop_loss
    else:
        profit_distance = entry - take_profit
        loss_distance = stop_loss - entry

    if profit_distance <= 0 or loss_distance <= 0:
        reasons.append("TP/SL 방향 검증 실패 — HOLD")
        return _make_hold(
            coin, symbol, strategy_type, expected_minutes, min_required_rr,
            entry, spread_bps, slippage_bps, reasons,
        )

    actual_rr = float(profit_distance / loss_distance)
    max_leverage = int(_cfg(config, "max_leverage", DECISION_MAX_LEVERAGE))
    requested_leverage = int(_read(strategy_signal, "leverage", max_leverage) or max_leverage)
    leverage = max(1, min(requested_leverage, max_leverage))

    max_margin_ratio = float(_cfg(
        config,
        "max_entry_margin_ratio",
        DECISION_MAX_ENTRY_MARGIN_RATIO,
    ))
    requested_margin_ratio = float(_read(
        strategy_signal,
        "margin_ratio",
        _cfg(config, "default_margin_ratio", min(0.02, max_margin_ratio)),
    ) or 0.0)
    margin_ratio = round(_clamp(requested_margin_ratio, 0.0, max_margin_ratio), 6)

    balance = _first_decimal(
        _read(account_state, "available_balance"),
        _read(account_state, "balance"),
        _read(account_state, "total_balance"),
        _cfg(config, "default_account_balance", 0.0),
    ) or _DECIMAL_ZERO
    margin = balance * Decimal(str(margin_ratio))
    notional = _q(margin * Decimal(str(leverage)))

    gross_profit = _q(notional * profit_distance / entry)
    gross_loss = _q(notional * loss_distance / entry)
    fees = _q(notional * Decimal(str(TAKER_FEE_RATE)) * Decimal("2"))
    slippage_cost = _q(
        notional * Decimal(str(slippage_bps)) / Decimal("10000") * Decimal("2")
    )
    net_profit = _q(gross_profit - fees - slippage_cost)
    net_loss = _q(gross_loss + fees + slippage_cost)

    reasons.append(
        f"isolated margin={margin_ratio:.2%}, leverage={leverage}x, "
        f"R:R={actual_rr:.2f}, fees/slippage 반영"
    )

    return TradeCandidate(
        action=action,
        coin=coin,
        symbol=symbol,
        strategy_type=strategy_type,
        expected_holding_minutes=expected_minutes,
        entry_price=_q(entry, _PRICE_Q),
        stop_loss=stop_loss,
        take_profit=take_profit,
        leverage=leverage,
        margin_ratio=margin_ratio,
        notional_size=notional,
        actual_rr=round(actual_rr, 4),
        min_required_rr=min_required_rr,
        expected_gross_profit=gross_profit,
        expected_gross_loss=gross_loss,
        expected_fees=fees,
        expected_slippage_cost=slippage_cost,
        expected_net_profit=net_profit,
        expected_net_loss=net_loss,
        liquidation_price=_liquidation_price(action, entry, leverage),
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        reasons=reasons,
    )
