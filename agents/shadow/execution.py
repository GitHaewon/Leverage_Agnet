"""
Shadow Trading 실행 엔진.

기존 ExecutionProvider 프로토콜을 구현한다.
OrchestratorDeps.execution = ShadowExecutionEngine(...) 으로 주입하면
파이프라인 코드 변경 없이 shadow 모드로 동작한다.

실행 순서:
  1. approved_validation 확인 또는 RiskValidatorProtocol.validate()
  2. Virtual FilledOrder 생성          — entry_price로 즉시 체결 가정 (API 없음)
  3. ShadowTradeRecord 저장            — store.save() 호출
  4. ExecutionResult(mode="paper") 반환
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Protocol

from agents.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    FilledOrder,
    RiskValidatorProtocol,
)
from agents.shadow.models import ShadowTradeRecord
from agents.shadow.pnl import (
    ShadowCostConfig,
    expected_fill_price,
    fill_fee,
    fill_slippage_cost,
)
from agents.shadow.experiment import ShadowExperimentConfig, plan_fast_exit
from agents.shadow.exchange_rules import get_symbol_rules
from agents.shadow.sizing import (
    ShadowSizingInput,
    ShadowSizingResult,
    evaluate_fixed_quantity_risk,
)
from agents.shadow.risk_state import UnresolvedOpenRiskError
from agents.risk.constants import PLAN_MAX_LEVERAGE

logger = logging.getLogger(__name__)

_ENTRY_SIDE: dict[str, str] = {"LONG": "BUY",  "SHORT": "SELL"}
_CLOSE_SIDE: dict[str, str] = {"LONG": "SELL", "SHORT": "BUY"}


def _direction(signal: object) -> str:
    if hasattr(signal, "direction"):
        return str(getattr(signal, "direction"))
    action = getattr(signal, "action", "")
    return str(getattr(action, "value", action))


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _decimal_or_zero(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except Exception:
            pass
    return Decimal("0")


class ShadowTradeStoreProtocol(Protocol):
    """ShadowTradeRecord 저장소 인터페이스.

    프로덕션: ShadowTradeRepository (SQLAlchemy AsyncSession 래핑)
    테스트:   InMemoryShadowStore
    """
    async def save(self, record: ShadowTradeRecord) -> bool | None: ...
    async def get_open_risk_usdt(
        self, user_id: str, strategy_version: str | None = None
    ) -> Decimal: ...
    async def get_loss_state(self, user_id: str, strategy_version: str) -> object: ...


class ShadowExecutionEngine:
    """
    Shadow Trading 실행 엔진.

    실제 Binance API를 호출하지 않으며, Risk 검증은 실거래와 동일하게 수행한다.
    """

    def __init__(
        self,
        risk_validator: RiskValidatorProtocol,
        store: ShadowTradeStoreProtocol,
        cost_config: ShadowCostConfig | None = None,
        experiment_config: ShadowExperimentConfig | None = None,
    ) -> None:
        self._validator = risk_validator
        self._store = store
        self._cost_config = cost_config or ShadowCostConfig()
        self._experiment_config = experiment_config or ShadowExperimentConfig()

    async def _open_risk(
        self, user_id: str, strategy_version: str | None = None
    ) -> Decimal:
        getter = getattr(self._store, "get_open_risk_usdt", None)
        if getter is None:
            return Decimal("0")
        value = await getter(user_id, strategy_version)
        return value if isinstance(value, Decimal) else Decimal("0")

    async def _baseline_risk(
        self, req: ExecutionRequest, signal: object, validation: object
    ) -> ShadowSizingResult | None:
        if not self._experiment_config.active:
            return None
        rules = get_symbol_rules(str(getattr(signal, "symbol", "")))
        if rules is None:
            return ShadowSizingResult(
                approved=False,
                rejection_code="UNSUPPORTED_SYMBOL_RULES",
                rejection_reason="baseline symbol has no Shadow exchange rules",
            )
        entry = getattr(signal, "entry_price")
        stop = getattr(signal, "stop_loss")
        take_profit = getattr(signal, "take_profit")
        holding_minutes = max(
            1, int(getattr(signal, "expected_holding_minutes", 1) or 1)
        )
        funding_intervals = max(
            1,
            int(
                (
                    Decimal(holding_minutes * 60)
                    / Decimal(self._cost_config.funding_interval_hours * 3600)
                ).to_integral_value(rounding=ROUND_CEILING)
            ),
        )
        equity = _decimal_or_zero(getattr(req.account, "total_balance", 0))
        available = _decimal_or_zero(getattr(req.account, "available_balance", 0))
        plan = str(getattr(req.user_ctx, "plan", "free") or "free")
        sizing_input = ShadowSizingInput(
            direction=_direction(signal),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take_profit,
            equity_usdt=equity,
            available_balance_usdt=available,
            risk_per_trade_pct=self._experiment_config.risk_per_trade_pct,
            open_strategy_risk_usdt=await self._open_risk(
                str(req.user_ctx.user_id), None
            ),
            max_portfolio_risk_pct=self._experiment_config.max_portfolio_risk_pct,
            max_single_position_margin_ratio=self._experiment_config.max_single_position_margin_ratio,
            margin_buffer_ratio=self._experiment_config.margin_buffer_ratio,
            plan_max_leverage=PLAN_MAX_LEVERAGE.get(plan, PLAN_MAX_LEVERAGE["free"]),
            user_max_leverage=int(getattr(req.user_ctx, "max_leverage", 1) or 1),
            system_max_leverage=self._experiment_config.system_max_leverage,
            shadow_safe_leverage_cap=self._experiment_config.safe_max_leverage,
            funding_intervals=funding_intervals,
            symbol_rules=rules,
            cost_config=self._cost_config,
        )
        return evaluate_fixed_quantity_risk(
            sizing_input,
            quantity=getattr(validation, "quantity"),
            leverage=getattr(validation, "final_leverage"),
            margin_usdt=getattr(validation, "margin_required_usdt"),
        )

    async def _save_fast_variant(
        self,
        *,
        req: ExecutionRequest,
        baseline: ShadowTradeRecord,
        validation: object,
        opened_at: datetime,
    ) -> None:
        if not self._experiment_config.fast_exit_enabled or req.candidate is None:
            return
        open_risk = await self._open_risk(str(req.user_ctx.user_id), None)
        plan = plan_fast_exit(
            req.candidate,
            user_ctx=req.user_ctx,
            account=req.account,
            open_strategy_risk_usdt=open_risk,
            baseline_quantity=getattr(validation, "quantity"),
            baseline_leverage=getattr(validation, "final_leverage"),
            baseline_margin_usdt=getattr(validation, "margin_required_usdt"),
            config=self._experiment_config,
            cost_config=self._cost_config,
        )
        loss_halt_code: str | None = None
        loss_halt_reason: str | None = None
        daily_loss = Decimal("0")
        daily_limit = Decimal("0")
        loss_getter = getattr(self._store, "get_loss_state", None)
        if loss_getter is not None:
            loss_state = await loss_getter(
                str(req.user_ctx.user_id), "fast_exit_v2"
            )
            daily_loss = getattr(loss_state, "daily_loss_usdt", Decimal("0"))
            consecutive = getattr(loss_state, "consecutive_losses", 0)
            daily_limit = _decimal_or_zero(
                getattr(req.account, "total_balance", 0)
            ) * _decimal_or_zero(
                getattr(req.user_ctx, "daily_loss_limit_pct", 0)
            )
            if isinstance(daily_loss, Decimal) and daily_limit > 0 and daily_loss >= daily_limit:
                loss_halt_code = "SHADOW_DAILY_LOSS_LIMIT"
                loss_halt_reason = "fast_exit_v2 daily loss limit reached"
            elif isinstance(consecutive, int) and consecutive >= 5:
                loss_halt_code = "SHADOW_CONSECUTIVE_LOSS_LIMIT"
                loss_halt_reason = "fast_exit_v2 consecutive loss limit reached"
        candidate = plan.exit_result.candidate or req.candidate
        sizing = plan.sizing_result
        sizing_approved = sizing is not None and sizing.approved
        if (
            loss_halt_code is None
            and sizing_approved
            and isinstance(daily_loss, Decimal)
            and daily_limit > 0
            and daily_loss + sizing.actual_max_loss_usdt > daily_limit
        ):
            loss_halt_code = "SHADOW_PROJECTED_DAILY_LOSS_LIMIT"
            loss_halt_reason = "fast_exit_v2 projected loss exceeds daily limit"
        quantity = (
            sizing.quantity
            if sizing_approved
            else getattr(validation, "quantity", Decimal("0"))
        )
        leverage = (
            sizing.leverage
            if sizing_approved
            else getattr(validation, "final_leverage", 1)
        )
        margin = (
            sizing.margin_usdt
            if sizing_approved
            else getattr(validation, "margin_required_usdt", Decimal("0"))
        )
        effective_approved = plan.approved and loss_halt_code is None
        if not effective_approved:
            quantity, leverage, margin = Decimal("0"), 1, Decimal("0")

        rejection_code = loss_halt_code or plan.exit_result.rejection_code
        rejection_reason = loss_halt_reason or plan.exit_result.rejection_reason
        if (
            loss_halt_code is None
            and plan.exit_result.approved
            and sizing is not None
            and not sizing.approved
        ):
            rejection_code = sizing.rejection_code
            rejection_reason = sizing.rejection_reason

        entry = candidate.entry_price
        tp = candidate.take_profit
        sl = candidate.stop_loss
        record = ShadowTradeRecord.open(
            user_id=str(req.user_ctx.user_id),
            coin=candidate.coin,
            symbol=candidate.symbol,
            direction=_direction(candidate),  # type: ignore[arg-type]
            entry_price=entry,
            tp_price=tp,
            sl_price=sl,
            quantity=quantity,
            leverage=leverage,
            opened_at=opened_at,
            strategy_version="fast_exit_v2",
            experiment_label=self._experiment_config.experiment_label,
            signal_id=baseline.signal_id,
            position_size_usdt=entry * quantity,
            margin_usdt=margin,
            tp_distance=abs(tp - entry),
            sl_distance=abs(entry - sl),
            expected_max_loss_usdt=(
                sizing.actual_max_loss_usdt
                if sizing_approved
                else getattr(validation, "max_loss_usdt", None)
            ),
            actual_max_loss_usdt=(
                sizing.actual_max_loss_usdt if sizing_approved else None
            ),
            risk_budget_usdt=sizing.risk_budget_usdt if sizing is not None else None,
            risk_budget_utilization=(
                sizing.risk_budget_utilization if sizing_approved else None
            ),
            leverage_reason=(
                sizing.leverage_reason
                if sizing_approved
                else "baseline sizing (risk sizing v2 disabled)"
            ),
            reviewer_input_summary=req.review_input_summary,
            reviewer_result=baseline.reviewer_result,
            reviewer_score=baseline.reviewer_score,
            market_regime=req.market_regime,
            entry_fee_usdt=(
                fill_fee(
                    expected_fill_price(
                        _direction(candidate),
                        entry,
                        self._cost_config.slippage_bps,
                        is_entry=True,
                    ),
                    quantity,
                    self._cost_config.taker_fee_rate,
                )
                if effective_approved
                else Decimal("0")
            ),
            entry_slippage_usdt=(
                fill_slippage_cost(entry, quantity, self._cost_config.slippage_bps)
                if effective_approved
                else Decimal("0")
            ),
            estimated_slippage_usdt=(
                fill_slippage_cost(entry, quantity, self._cost_config.slippage_bps)
                if effective_approved
                else Decimal("0")
            ),
            max_hold_seconds=(
                self._experiment_config.fast_exit.max_hold_seconds
                if self._experiment_config.fast_exit is not None
                else None
            ),
            rejection_code=rejection_code,
            rejection_reason=rejection_reason,
        )
        if not effective_approved:
            record.status = "REJECTED"
        await self._store.save(record)

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        try:
            # ── STEP 1: Risk Validation 확인 ────────────────────────────────
            if req.approved_validation is not None:
                validation = req.approved_validation
                signal = req.candidate or req.signal
            else:
                validation = await self._validator.validate(
                    signal=req.signal,
                    ctx=req.user_ctx,
                    account=req.account,
                    daily_loss_usdt=req.daily_loss_usdt,
                    weekly_loss_usdt=req.weekly_loss_usdt,
                    weekly_limit_usdt=req.weekly_limit_usdt,
                    consecutive_losses=req.consecutive_losses,
                    open_positions_count=req.open_positions_count,
                    same_coin_position=req.same_coin_position,
                )
                signal = req.signal

            if not validation.approved:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code=validation.rejection_code,
                    rejection_reason=validation.rejection_reason,
                    validation=validation,
                )

            if req.approved_validation is not None:
                if req.final_decision is None or req.candidate is None:
                    return ExecutionResult(
                        approved=False,
                        executed=False,
                        mode="paper",
                        rejection_code="FINAL_DECISION_MISSING",
                        rejection_reason="FinalDecision and TradeCandidate are required",
                        validation=validation,
                    )

            direction = _direction(signal)
            if direction not in ("LONG", "SHORT"):
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="INVALID_DIRECTION",
                    rejection_reason="Execution direction must be LONG or SHORT",
                    validation=validation,
                )
            if getattr(signal, "stop_loss", None) is None:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="ORDER_003",
                    rejection_reason="stop_loss is required before shadow execution",
                    validation=validation,
                )
            if getattr(signal, "take_profit", None) is None:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="TAKE_PROFIT_MISSING",
                    rejection_reason="take_profit is required before shadow execution",
                    validation=validation,
                )

            try:
                baseline_risk = await self._baseline_risk(req, signal, validation)
            except UnresolvedOpenRiskError as exc:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code="OPEN_RISK_UNRESOLVED",
                    rejection_reason=str(exc),
                    validation=validation,
                )
            if baseline_risk is not None and not baseline_risk.approved:
                return ExecutionResult(
                    approved=False,
                    executed=False,
                    mode="paper",
                    rejection_code=baseline_risk.rejection_code,
                    rejection_reason=baseline_risk.rejection_reason,
                    validation=validation,
                )

            # ── STEP 2: Virtual Fill ─────────────────────────────────────────
            now = datetime.now(timezone.utc)
            qty = validation.quantity
            entry_px: Decimal = signal.entry_price
            tp_px: Decimal = signal.take_profit
            sl_px: Decimal = signal.stop_loss

            record = ShadowTradeRecord.open(
                user_id=str(req.user_ctx.user_id),
                coin=signal.coin,
                symbol=signal.symbol,
                direction=direction,
                entry_price=entry_px,
                tp_price=tp_px,
                sl_price=sl_px,
                quantity=qty,
                leverage=validation.final_leverage,
                opened_at=now,
                strategy_version=(
                    "baseline_v1"
                    if self._experiment_config.active
                    else req.strategy_version or "unknown"
                ),
                experiment_label=(
                    self._experiment_config.experiment_label
                    if self._experiment_config.active
                    else None
                ),
                signal_id=(
                    str(getattr(req.signal, "signal_id", None))
                    if getattr(req.signal, "signal_id", None)
                    else None
                ),
                position_size_usdt=entry_px * qty,
                margin_usdt=validation.margin_required_usdt,
                tp_distance=abs(tp_px - entry_px),
                sl_distance=abs(entry_px - sl_px),
                expected_max_loss_usdt=validation.max_loss_usdt,
                actual_max_loss_usdt=(
                    baseline_risk.actual_max_loss_usdt
                    if baseline_risk is not None
                    else validation.max_loss_usdt
                ),
                risk_budget_usdt=(
                    baseline_risk.risk_budget_usdt
                    if baseline_risk is not None
                    else None
                ),
                risk_budget_utilization=(
                    baseline_risk.risk_budget_utilization
                    if baseline_risk is not None
                    else None
                ),
                leverage_reason="; ".join(
                    str(reason)[:200] for reason in getattr(req.candidate, "reasons", [])[:3]
                ) or "risk engine limit applied",
                reviewer_input_summary=req.review_input_summary,
                reviewer_result=_enum_value(
                    getattr(
                        getattr(req.final_decision, "ai_review", None),
                        "review_action",
                        None,
                    )
                ),
                reviewer_score=getattr(
                    getattr(req.final_decision, "ai_review", None), "confidence", None
                ),
                market_regime=req.market_regime,
                entry_fee_usdt=fill_fee(
                    expected_fill_price(
                        direction,
                        entry_px,
                        self._cost_config.slippage_bps,
                        is_entry=True,
                    ),
                    qty,
                    self._cost_config.taker_fee_rate,
                ),
                exit_fee_usdt=Decimal("0"),
                estimated_slippage_usdt=fill_slippage_cost(
                    entry_px, qty, self._cost_config.slippage_bps
                ),
                entry_slippage_usdt=fill_slippage_cost(
                    entry_px, qty, self._cost_config.slippage_bps
                ),
                data_error=any(
                    err.get("agent") in {"market_data", "technical", "strategy"}
                    for err in req.pipeline_errors
                ),
                system_error=any(
                    err.get("agent") not in {"market_data", "technical", "strategy"}
                    for err in req.pipeline_errors
                ),
            )

            # ── STEP 3: Persist ──────────────────────────────────────────────
            await self._store.save(record)
            try:
                await self._save_fast_variant(
                    req=req,
                    baseline=record,
                    validation=validation,
                    opened_at=now,
                )
            except Exception:
                # Experiment failures are isolated from baseline_v1.
                logger.exception(
                    "fast_exit_v2 isolated failure signal_id=%s", record.signal_id
                )

            logger.info(
                "shadow_trade_opened id=%s user=%s %s/%s "
                "entry=%s tp=%s sl=%s qty=%s lev=%dx",
                record.id, req.user_ctx.user_id,
                signal.coin, direction,
                entry_px, tp_px, sl_px, qty, validation.final_leverage,
            )

            def _fill(purpose: str, side: str, order_type: str, price: Decimal) -> FilledOrder:
                return FilledOrder(
                    exchange_order_id=f"shadow-{purpose}-{record.id}",
                    symbol=signal.symbol,
                    purpose=purpose,  # type: ignore[arg-type]
                    side=side,
                    order_type=order_type,
                    quantity=qty,
                    avg_fill_price=price,
                    fee_usdt=Decimal("0"),
                    filled_at=now,
                )

            return ExecutionResult(
                approved=True,
                executed=True,
                mode="paper",
                validation=validation,
                entry_order=_fill(
                    "entry",
                    _ENTRY_SIDE[direction],
                    "MARKET",
                    entry_px,
                ),
                tp_order=_fill(
                    "take_profit",
                    _CLOSE_SIDE[direction],
                    "TAKE_PROFIT_MARKET",
                    tp_px,
                ),
                sl_order=_fill(
                    "stop_loss",
                    _CLOSE_SIDE[direction],
                    "STOP_MARKET",
                    sl_px,
                ),
                warnings=list(validation.warnings),
            )

        except Exception as exc:
            logger.error("ShadowExecutionEngine error: %s", exc, exc_info=True)
            return ExecutionResult(
                approved=False,
                executed=False,
                mode="paper",
                rejection_code="SYSTEM_ERROR",
                rejection_reason=f"SYSTEM_ERROR: {type(exc).__name__}",
            )
