"""
Final decision engine — 최종 액션 결정.

규칙:
  - AI 호출 없음. 주문 없음. 순수 결정 함수.
  - AI 승인만으로는 절대 거래를 허용하지 않는다.
  - RiskEngine 거부/누락은 항상 HOLD다.
  - 누락·불확실성·실패는 안전하게 HOLD로 귀결된다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from agents.decision.constants import (
    MIN_AI_REVIEW_CONFIDENCE,
    MIN_EXPECTED_NET_PROFIT_PCT,
    REJECT_ON_CRITICAL_CONTRADICTION,
)
from agents.decision.models import (
    AIReviewAction,
    FinalAction,
    FinalDecision,
    StrategyType,
    TradeCandidate,
)


def _read(data: Any, key: str, default: Any = None) -> Any:
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


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


def _hold(
    reason: str,
    candidate: TradeCandidate | None = None,
    ai_review: Any | None = None,
    risk_result: Any | None = None,
) -> FinalDecision:
    return FinalDecision(
        action=FinalAction.HOLD,
        reason=reason,
        candidate=candidate,
        ai_review=ai_review,
        risk_result=risk_result,
    )


def _risk_passed(risk_result: Any) -> bool:
    passed = _read(risk_result, "passed")
    if passed is not None:
        return bool(passed)

    approved = _read(risk_result, "approved")
    if approved is not None:
        return bool(approved)

    return False


def _min_expected_profit(candidate: TradeCandidate, config: Any) -> Decimal:
    explicit = _read(config, "min_expected_net_profit")
    if explicit is not None:
        return Decimal(str(explicit))

    explicit = _read(_read(config, "decision"), "min_expected_net_profit")
    if explicit is not None:
        return Decimal(str(explicit))

    pct = Decimal(str(_cfg(
        config,
        "min_expected_net_profit_pct",
        MIN_EXPECTED_NET_PROFIT_PCT,
    )))
    return candidate.notional_size * pct


def decide_final_action(
    candidate: TradeCandidate | None,
    ai_review: Any | None,
    risk_result: Any | None,
    config: Any | None = None,
) -> FinalDecision:
    """
    후보·AI 리뷰·RiskEngine 결과를 최종 액션으로 조립한다.

    Returns
    -------
    FinalDecision
      action: LONG / SHORT / HOLD
      reason: 사람이 읽을 수 있는 최종 결정 근거
    """
    if candidate is None:
        return _hold("후보가 없습니다 — HOLD", None, ai_review, risk_result)

    if candidate.action == FinalAction.HOLD:
        return _hold("candidate.action=HOLD — 실행 없음", candidate, ai_review, risk_result)

    if candidate.action not in (FinalAction.LONG, FinalAction.SHORT):
        return _hold(
            "candidate.action이 LONG/SHORT가 아닙니다 — HOLD",
            candidate,
            ai_review,
            risk_result,
        )

    if candidate.strategy_type == StrategyType.UNKNOWN:
        return _hold("strategy_type=UNKNOWN — HOLD", candidate, ai_review, risk_result)

    if risk_result is None:
        return _hold(
            "RiskEngine 결과가 없습니다 — HOLD",
            candidate,
            ai_review,
            risk_result,
        )

    if not _risk_passed(risk_result):
        reason = (
            _read(risk_result, "rejection_reason")
            or "RiskEngine이 거래를 거부했습니다"
        )
        return _hold(str(reason), candidate, ai_review, risk_result)

    if ai_review is None:
        return _hold("AI 리뷰 결과가 없습니다 — HOLD", candidate, ai_review, risk_result)

    if _read(ai_review, "review_action") == AIReviewAction.REJECT:
        reason = _read(ai_review, "reason_summary") or "AI reviewer rejected candidate"
        return _hold(str(reason), candidate, ai_review, risk_result)

    reject_on_critical = bool(_cfg(
        config,
        "reject_on_critical_contradiction",
        REJECT_ON_CRITICAL_CONTRADICTION,
    ))
    if bool(_read(ai_review, "critical_contradiction", False)) and reject_on_critical:
        return _hold(
            "AI reviewer critical_contradiction=True — HOLD",
            candidate,
            ai_review,
            risk_result,
        )

    min_confidence = float(_cfg(
        config,
        "min_ai_review_confidence",
        MIN_AI_REVIEW_CONFIDENCE,
    ))
    confidence = float(_read(ai_review, "confidence", 0.0) or 0.0)
    if confidence < min_confidence:
        return _hold(
            f"AI reviewer confidence {confidence:.2f} < required {min_confidence:.2f} — HOLD",
            candidate,
            ai_review,
            risk_result,
        )

    min_profit = _min_expected_profit(candidate, config)
    if candidate.expected_net_profit is None or candidate.expected_net_profit <= min_profit:
        return _hold(
            f"expected_net_profit {candidate.expected_net_profit} <= minimum {min_profit} — HOLD",
            candidate,
            ai_review,
            risk_result,
        )

    action = candidate.action
    return FinalDecision(
        action=action,
        reason=(
            f"{action.value}: deterministic candidate passed RiskEngine and AI reviewer "
            f"approved with confidence {confidence:.2f}"
        ),
        candidate=candidate,
        ai_review=ai_review,
        risk_result=risk_result,
    )
