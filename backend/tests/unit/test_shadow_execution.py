"""
Shadow Trading Mode 단위 테스트.

검증 항목:
  1.  Risk rejected → ExecutionResult(approved=False, executed=False)
  2.  Risk approved → store.save() 1회 호출
  3.  Risk approved → ExecutionResult(mode="paper", executed=True)
  4.  가상 FilledOrder의 price가 signal 가격과 일치
  5.  entry_order.exchange_order_id에 "shadow-entry-" 접두사 포함
  6.  store.save() 예외 → SYSTEM_ERROR 격리 (파이프라인 영향 없음)
  7.  ShadowTradeRecord.close() LONG TP_HIT — PnL = (exit - entry) * qty
  8.  ShadowTradeRecord.close() SHORT SL_HIT — PnL = (entry - exit) * qty
  9.  ShadowTradeRecord.close() LONG SL_HIT — 손실(음수 PnL)
  10. ShadowTradeRecord.close() Duration = closed_at - opened_at
  11. ShadowTradeRecord.open() — status 기본값 "OPEN"
  12. check_and_close_shadow_trades — LONG TP_HIT
  13. check_and_close_shadow_trades — SHORT SL_HIT
  14. check_and_close_shadow_trades — 가격 미도달 시 청산 안 함
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.execution.models import ExecutionRequest
from agents.shadow.execution import ShadowExecutionEngine
from agents.shadow.models import ShadowTradeRecord
from agents.shadow.pnl import ShadowCostConfig
from agents.shadow.experiment import ShadowExperimentConfig
from agents.shadow.risk_state import UnresolvedOpenRiskError
from agents.shadow.strategies.fast_exit_v2 import FastExitConfig


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────────

def _signal(
    direction: str = "LONG",
    entry_price: str = "50000",
    tp_price: str = "55000",
    sl_price: str = "48000",
    coin: str = "BTC",
    symbol: str = "BTCUSDT",
) -> MagicMock:
    s = MagicMock()
    s.direction = direction
    s.entry_price = Decimal(entry_price)
    s.take_profit = Decimal(tp_price)
    s.stop_loss = Decimal(sl_price)
    s.coin = coin
    s.symbol = symbol
    s.signal_id = uuid.uuid4()
    return s


def _validation(approved: bool = True, qty: str = "0.01", leverage: int = 5) -> MagicMock:
    v = MagicMock()
    v.approved = approved
    v.quantity = Decimal(qty)
    v.final_leverage = leverage
    v.rejection_code = "RISK_FAIL" if not approved else None
    v.rejection_reason = "test rejection" if not approved else None
    v.warnings = []
    v.margin_required_usdt = Decimal("100")
    v.max_loss_usdt = Decimal("25")
    return v


def _user_ctx(user_id: str = "test-user-001") -> MagicMock:
    ctx = MagicMock()
    ctx.user_id = user_id
    return ctx


def _req(signal=None, validation_result=None, direction: str = "LONG") -> tuple[ExecutionRequest, MagicMock]:
    sig = signal or _signal(direction=direction)
    account = MagicMock()
    account.balance = Decimal("10000")
    user_ctx = _user_ctx()

    req = ExecutionRequest(
        signal=sig,
        user_ctx=user_ctx,
        account=account,
        daily_loss_usdt=Decimal("50"),
        weekly_loss_usdt=Decimal("100"),
        weekly_limit_usdt=Decimal("500"),
        consecutive_losses=0,
        open_positions_count=0,
        same_coin_position=None,
    )
    val = validation_result or _validation()
    return req, val


def _make_engine(validation: MagicMock) -> tuple[ShadowExecutionEngine, AsyncMock, AsyncMock]:
    risk = AsyncMock()
    risk.validate = AsyncMock(return_value=validation)
    store = AsyncMock()
    store.save = AsyncMock()
    engine = ShadowExecutionEngine(risk_validator=risk, store=store)
    return engine, risk, store


# ── Group 1: Risk 검증 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_rejected_returns_not_approved():
    req, val = _req(validation_result=_validation(approved=False))
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert not result.approved
    assert not result.executed
    assert result.rejection_code == "RISK_FAIL"


@pytest.mark.asyncio
async def test_risk_rejected_does_not_call_store():
    req, val = _req(validation_result=_validation(approved=False))
    engine, _, store = _make_engine(val)
    await engine.execute(req)
    store.save.assert_not_awaited()


# ── Group 2: 정상 실행 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_execution_calls_store_once():
    req, val = _req()
    engine, _, store = _make_engine(val)
    await engine.execute(req)
    store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_execution_persists_trade_fields():
    sig = _signal(
        direction="LONG",
        entry_price="50000",
        tp_price="55000",
        sl_price="48000",
    )
    req, val = _req(signal=sig, validation_result=_validation(qty="0.0123", leverage=7))
    engine, _, store = _make_engine(val)

    await engine.execute(req)

    record = store.save.await_args.args[0]
    assert record.entry_price == Decimal("50000")
    assert record.tp_price == Decimal("55000")
    assert record.sl_price == Decimal("48000")
    assert record.quantity == Decimal("0.0123")
    assert record.leverage == 7


@pytest.mark.asyncio
async def test_successful_execution_persists_performance_context():
    req, val = _req()
    req.strategy_version = "decision-pipeline-v2"
    req.market_regime = "TREND_UP"
    req.review_input_summary = {"chart_long_score": 72.0}
    req.candidate = MagicMock()
    req.candidate.reasons = ["trend confirmed"]
    req.candidate.expected_fees = Decimal("2")
    req.candidate.expected_slippage_cost = Decimal("0.5")
    review = MagicMock()
    review.review_action.value = "APPROVE"
    review.confidence = 0.84
    req.final_decision = MagicMock(ai_review=review)

    engine, _, store = _make_engine(val)
    await engine.execute(req)

    record = store.save.await_args.args[0]
    assert record.strategy_version == "decision-pipeline-v2"
    assert record.signal_id == str(req.signal.signal_id)
    assert record.position_size_usdt == Decimal("500.00")
    assert record.margin_usdt == Decimal("100")
    assert record.tp_distance == Decimal("5000")
    assert record.sl_distance == Decimal("2000")
    assert record.expected_max_loss_usdt == Decimal("25")
    assert record.reviewer_input_summary == {"chart_long_score": 72.0}
    assert record.reviewer_result == "APPROVE"
    assert record.reviewer_score == 0.84
    assert record.market_regime == "TREND_UP"
    assert record.entry_fee_usdt == Decimal("0.20010000")
    assert record.exit_fee_usdt == Decimal("0")
    assert record.estimated_slippage_usdt == Decimal("0.25000000")
    assert record.status == "OPEN"


def test_close_calculates_gross_and_net_pnl_with_costs():
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT", direction="LONG",
        entry_price=Decimal("100"), tp_price=Decimal("120"),
        sl_price=Decimal("90"), quantity=Decimal("2"), leverage=2,
    )
    record.close(Decimal("120"), "TP_HIT")
    assert record.gross_pnl_usdt == Decimal("40.0")
    assert record.entry_fee_usdt == Decimal("0.08004000")
    assert record.exit_fee_usdt == Decimal("0.09595200")
    assert record.entry_slippage_usdt == Decimal("0.10000000")
    assert record.exit_slippage_usdt == Decimal("0.12000000")
    assert record.estimated_slippage_usdt == Decimal("0.22000000")
    assert record.net_pnl_usdt == Decimal("39.60400800")
    assert record.exit_reason == "TP_HIT"
    assert record.status == "TP_HIT"


@pytest.mark.asyncio
async def test_successful_execution_returns_paper_mode():
    req, val = _req()
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.approved
    assert result.executed
    assert result.mode == "paper"


@pytest.mark.asyncio
async def test_virtual_orders_use_signal_prices():
    sig = _signal(entry_price="50000", tp_price="55000", sl_price="48000")
    req, val = _req(signal=sig)
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.avg_fill_price == Decimal("50000")
    assert result.tp_order.avg_fill_price == Decimal("55000")
    assert result.sl_order.avg_fill_price == Decimal("48000")


@pytest.mark.asyncio
async def test_virtual_order_ids_contain_shadow_prefix():
    req, val = _req()
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.exchange_order_id.startswith("shadow-entry-")
    assert result.tp_order.exchange_order_id.startswith("shadow-take_profit-")
    assert result.sl_order.exchange_order_id.startswith("shadow-stop_loss-")


@pytest.mark.asyncio
async def test_long_entry_side_is_buy():
    req, val = _req(direction="LONG")
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.side == "BUY"
    assert result.tp_order.side == "SELL"
    assert result.sl_order.side == "SELL"


@pytest.mark.asyncio
async def test_short_entry_side_is_sell():
    req, val = _req(direction="SHORT", signal=_signal(direction="SHORT"))
    engine, _, _ = _make_engine(val)
    result = await engine.execute(req)
    assert result.entry_order.side == "SELL"
    assert result.tp_order.side == "BUY"
    assert result.sl_order.side == "BUY"


# ── Group 3: store 예외 격리 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_exception_returns_system_error():
    req, val = _req()
    engine, _, store = _make_engine(val)
    store.save = AsyncMock(side_effect=RuntimeError("DB down"))
    result = await engine.execute(req)
    assert not result.approved
    assert result.rejection_code == "SYSTEM_ERROR"


@pytest.mark.asyncio
async def test_store_exception_does_not_propagate():
    req, val = _req()
    engine, _, store = _make_engine(val)
    store.save = AsyncMock(side_effect=OSError("disk full"))
    result = await engine.execute(req)  # should not raise
    assert result is not None


# ── Group 4: ShadowTradeRecord 도메인 로직 ────────────────────────────────────

def test_open_classmethod_sets_status_open():
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    assert record.status == "OPEN"
    assert record.exit_price is None
    assert record.pnl_usdt is None


def test_long_tp_hit_pnl():
    """LONG TP_HIT: exit=55000, entry=50000, qty=0.01 → PnL = 50 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("55000"), "TP_HIT")
    assert record.pnl_usdt == pytest.approx(50.0)
    assert record.status == "TP_HIT"
    assert record.exit_price == Decimal("55000")


def test_long_sl_hit_negative_pnl():
    """LONG SL_HIT: exit=48000, entry=50000, qty=0.01 → PnL = -20 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("48000"), "SL_HIT")
    assert record.pnl_usdt == pytest.approx(-20.0)
    assert record.status == "SL_HIT"


def test_short_tp_hit_pnl():
    """SHORT TP_HIT: entry=50000, exit=45000, qty=0.01 → PnL = 50 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="SHORT",
        entry_price=Decimal("50000"),
        tp_price=Decimal("45000"),
        sl_price=Decimal("52000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("45000"), "TP_HIT")
    assert record.pnl_usdt == pytest.approx(50.0)


def test_short_sl_hit_negative_pnl():
    """SHORT SL_HIT: entry=50000, exit=52000, qty=0.01 → PnL = -20 USDT"""
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="SHORT",
        entry_price=Decimal("50000"),
        tp_price=Decimal("45000"),
        sl_price=Decimal("52000"),
        quantity=Decimal("0.01"),
        leverage=5,
    )
    record.close(Decimal("52000"), "SL_HIT")
    assert record.pnl_usdt == pytest.approx(-20.0)


def test_duration_seconds():
    opened = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    closed = datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc)  # +1h
    record = ShadowTradeRecord.open(
        user_id="u1", coin="BTC", symbol="BTCUSDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        tp_price=Decimal("55000"),
        sl_price=Decimal("48000"),
        quantity=Decimal("0.01"),
        leverage=5,
        opened_at=opened,
    )
    record.close(Decimal("55000"), "TP_HIT", closed_at=closed)
    assert record.duration_seconds == pytest.approx(3600.0)
    assert record.closed_at == closed


# ── Group 5: Monitor 로직 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_closes_long_tp_hit():
    """LONG trade: current_price >= tp_price → TP_HIT."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "BTCUSDT"
    trade.direction = "LONG"
    trade.entry_price = Decimal("50000")
    trade.tp_price = Decimal("55000")
    trade.sl_price = Decimal("48000")
    trade.quantity = Decimal("0.01")
    trade.opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
    trade.max_hold_seconds = None

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    session_mock = AsyncMock()

    from unittest.mock import patch
    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"BTCUSDT": Decimal("55500")},
            session_mock,
            ShadowCostConfig(
                taker_fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                funding_rate_per_interval=Decimal("0"),
            ),
        )

    assert closed == 1
    call_kwargs = repo_mock.close_trade.call_args
    assert call_kwargs.kwargs["status"] == "TP_HIT"
    assert call_kwargs.kwargs["exit_price"] == Decimal("55000")
    assert call_kwargs.kwargs["gross_pnl_usdt"] == Decimal("50.0")
    assert call_kwargs.kwargs["net_pnl_usdt"] == Decimal("50.00000000")
    assert call_kwargs.kwargs["exit_reason"] == "TP_HIT"
    repo_mock.update_excursions.assert_awaited_once()


@pytest.mark.asyncio
async def test_monitor_closes_short_sl_hit():
    """SHORT trade: current_price >= sl_price → SL_HIT."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "ETHUSDT"
    trade.direction = "SHORT"
    trade.entry_price = Decimal("3000")
    trade.tp_price = Decimal("2700")
    trade.sl_price = Decimal("3200")
    trade.quantity = Decimal("0.1")
    trade.opened_at = datetime.now(timezone.utc) - timedelta(hours=1)
    trade.max_hold_seconds = None

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"ETHUSDT": Decimal("3250")},
            AsyncMock(),
            ShadowCostConfig(
                taker_fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                funding_rate_per_interval=Decimal("0"),
            ),
        )

    assert closed == 1
    assert repo_mock.close_trade.call_args.kwargs["status"] == "SL_HIT"


@pytest.mark.asyncio
async def test_monitor_skips_trade_price_not_reached():
    """TP/SL 미도달 시 청산하지 않는다."""
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "BTCUSDT"
    trade.direction = "LONG"
    trade.entry_price = Decimal("50000")
    trade.tp_price = Decimal("55000")
    trade.sl_price = Decimal("48000")
    trade.quantity = Decimal("0.01")
    trade.opened_at = datetime.now(timezone.utc)
    trade.max_hold_seconds = None

    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])
    repo_mock.close_trade = AsyncMock()

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"BTCUSDT": Decimal("52000")},  # 중간 가격 — TP/SL 미도달
            AsyncMock(),
            ShadowCostConfig(
                taker_fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                funding_rate_per_interval=Decimal("0"),
            ),
        )

    assert closed == 0
    repo_mock.close_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_monitor_marks_missing_price_as_data_error():
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock(id=uuid.uuid4(), symbol="BTCUSDT", direction="LONG")
    trade.max_hold_seconds = None
    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {},
            AsyncMock(),
            ShadowCostConfig(
                taker_fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                funding_rate_per_interval=Decimal("0"),
            ),
        )

    assert closed == 0
    repo_mock.mark_data_error.assert_awaited_once_with(trade.id)


class _Action(str, Enum):
    LONG = "LONG"


@dataclass
class _Candidate:
    action: _Action = _Action.LONG
    coin: str = "BTC"
    symbol: str = "BTCUSDT"
    entry_price: Decimal = Decimal("50000")
    take_profit: Decimal = Decimal("51000")
    stop_loss: Decimal = Decimal("49500")
    expected_holding_minutes: int = 60
    actual_rr: float = 2.0
    reasons: list[str] = field(default_factory=lambda: ["source"])


@pytest.mark.asyncio
async def test_enabled_experiment_saves_independent_baseline_and_fast_records():
    candidate = _Candidate()
    source_prices = (candidate.take_profit, candidate.stop_loss)
    req, val = _req(signal=_signal())
    req.candidate = candidate
    req.final_decision = MagicMock()
    req.approved_validation = val
    req.user_ctx.plan = "pro"
    req.user_ctx.max_leverage = 10
    req.account.total_balance = Decimal("10000")
    req.account.available_balance = Decimal("10000")
    req.user_ctx.plan = "pro"
    req.user_ctx.max_leverage = 10
    req.user_ctx.daily_loss_limit_pct = 0.03
    req.account.total_balance = Decimal("10000")
    req.account.available_balance = Decimal("10000")
    store = AsyncMock()
    store.save = AsyncMock()
    store.get_open_risk_usdt = AsyncMock(return_value=Decimal("0"))
    store.get_loss_state = AsyncMock(
        return_value=MagicMock(
            daily_loss_usdt=Decimal("0"), consecutive_losses=0
        )
    )
    engine = ShadowExecutionEngine(
        risk_validator=AsyncMock(),
        store=store,
        cost_config=ShadowCostConfig(),
        experiment_config=ShadowExperimentConfig(
            fast_exit_enabled=True,
            risk_sizing_enabled=True,
            experiment_label="ab-test",
            fast_exit=FastExitConfig(
                tp_pct=Decimal("0.006"),
                sl_pct=Decimal("0.003"),
                min_sl_pct=Decimal("0.0025"),
                max_hold_seconds=900,
                min_rr=Decimal("2"),
                min_tp_cost_multiple=Decimal("1"),
            ),
        ),
    )

    result = await engine.execute(req)

    assert result.approved and result.executed
    assert store.save.await_count == 2
    baseline = store.save.await_args_list[0].args[0]
    fast = store.save.await_args_list[1].args[0]
    assert baseline.strategy_version == "baseline_v1"
    assert fast.strategy_version == "fast_exit_v2"
    assert baseline.signal_id == fast.signal_id
    assert baseline.experiment_label == fast.experiment_label == "ab-test"
    assert fast.tp_price != baseline.tp_price
    assert fast.actual_max_loss_usdt <= fast.risk_budget_usdt
    assert candidate.take_profit == source_prices[0]
    assert candidate.stop_loss == source_prices[1]


@pytest.mark.asyncio
async def test_unresolved_open_risk_rejects_experiment_without_uncaught_exception():
    req, val = _req(signal=_signal())
    req.candidate = _Candidate()
    req.final_decision = MagicMock()
    req.approved_validation = val
    req.user_ctx.plan = "pro"
    req.user_ctx.max_leverage = 10
    req.account.total_balance = Decimal("10000")
    req.account.available_balance = Decimal("10000")

    store = AsyncMock()
    store.save = AsyncMock()
    store.get_open_risk_usdt = AsyncMock(
        side_effect=UnresolvedOpenRiskError("OPEN_RISK_UNRESOLVED: trade-1")
    )
    engine = ShadowExecutionEngine(
        risk_validator=AsyncMock(),
        store=store,
        experiment_config=ShadowExperimentConfig(
            fast_exit_enabled=True,
            risk_sizing_enabled=True,
            fast_exit=FastExitConfig(
                tp_pct=Decimal("0.006"),
                sl_pct=Decimal("0.003"),
                min_sl_pct=Decimal("0.0025"),
                max_hold_seconds=900,
                min_rr=Decimal("2"),
                min_tp_cost_multiple=Decimal("1"),
            ),
        ),
    )

    result = await engine.execute(req)

    assert result is not None
    assert not result.approved
    assert not result.executed
    assert result.rejection_code == "OPEN_RISK_UNRESOLVED"
    assert "OPEN_RISK_UNRESOLVED" in result.rejection_reason
    store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_fast_variant_failure_does_not_change_baseline_result():
    candidate = _Candidate()
    req, val = _req(signal=_signal())
    req.candidate = candidate
    req.final_decision = MagicMock()
    req.approved_validation = val
    req.user_ctx.plan = "pro"
    req.user_ctx.max_leverage = 10
    req.user_ctx.daily_loss_limit_pct = 0.03
    req.account.total_balance = Decimal("10000")
    req.account.available_balance = Decimal("10000")
    store = AsyncMock()
    store.save = AsyncMock()
    store.get_open_risk_usdt = AsyncMock(return_value=Decimal("0"))
    engine = ShadowExecutionEngine(
        risk_validator=AsyncMock(),
        store=store,
        experiment_config=ShadowExperimentConfig(
            fast_exit_enabled=True,
            risk_sizing_enabled=False,
            fast_exit=None,  # invalid on purpose; isolated experiment failure
        ),
    )

    result = await engine.execute(req)

    assert result.approved and result.executed
    assert store.save.await_count == 1
    assert store.save.await_args.args[0].strategy_version == "baseline_v1"


@pytest.mark.asyncio
async def test_fast_rejection_is_recorded_without_rejecting_baseline():
    req, val = _req(signal=_signal())
    req.candidate = _Candidate()
    req.final_decision = MagicMock()
    req.approved_validation = val
    req.user_ctx.plan = "pro"
    req.user_ctx.max_leverage = 10
    req.user_ctx.daily_loss_limit_pct = 0.03
    req.account.total_balance = Decimal("10000")
    req.account.available_balance = Decimal("10000")
    store = AsyncMock()
    store.save = AsyncMock()
    store.get_open_risk_usdt = AsyncMock(return_value=Decimal("0"))
    store.get_loss_state = AsyncMock(
        return_value=MagicMock(
            daily_loss_usdt=Decimal("0"), consecutive_losses=0
        )
    )
    engine = ShadowExecutionEngine(
        risk_validator=AsyncMock(),
        store=store,
        cost_config=ShadowCostConfig(
            taker_fee_rate=Decimal("0.01"),
            slippage_bps=Decimal("100"),
            funding_rate_per_interval=Decimal("0.001"),
        ),
        experiment_config=ShadowExperimentConfig(
            fast_exit_enabled=True,
            risk_sizing_enabled=False,
            fast_exit=FastExitConfig(
                tp_pct=Decimal("0.006"),
                sl_pct=Decimal("0.003"),
                min_sl_pct=Decimal("0.0025"),
                max_hold_seconds=900,
                min_rr=Decimal("2"),
                min_tp_cost_multiple=Decimal("1"),
            ),
        ),
    )

    result = await engine.execute(req)

    baseline, fast = [call.args[0] for call in store.save.await_args_list]
    assert result.approved and baseline.status == "OPEN"
    assert fast.status == "REJECTED"
    assert fast.rejection_code in {
        "NON_POSITIVE_TP_NET",
        "TP_COST_MULTIPLE_NOT_MET",
    }


@pytest.mark.asyncio
async def test_monitor_closes_at_max_hold_with_market_price():
    from app.workers.shadow_monitor_worker import check_and_close_shadow_trades
    from unittest.mock import patch

    trade = MagicMock()
    trade.id = uuid.uuid4()
    trade.symbol = "BTCUSDT"
    trade.direction = "LONG"
    trade.entry_price = Decimal("50000")
    trade.tp_price = Decimal("55000")
    trade.sl_price = Decimal("48000")
    trade.quantity = Decimal("0.01")
    trade.margin_usdt = Decimal("100")
    trade.max_hold_seconds = 60
    trade.opened_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    repo_mock = AsyncMock()
    repo_mock.get_open_trades = AsyncMock(return_value=[trade])

    with patch(
        "app.repositories.shadow_trade_repository.ShadowTradeRepository",
        return_value=repo_mock,
    ):
        closed = await check_and_close_shadow_trades(
            {"BTCUSDT": Decimal("50100")},
            AsyncMock(),
            ShadowCostConfig(
                taker_fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                funding_rate_per_interval=Decimal("0"),
            ),
        )

    assert closed == 1
    kwargs = repo_mock.close_trade.await_args.kwargs
    assert kwargs["status"] == "MAX_HOLD"
    assert kwargs["exit_reason"] == "MAX_HOLD"
    assert kwargs["exit_price"] == Decimal("50100")
