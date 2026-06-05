"""
RiskEngine 파이프라인 단위 테스트.
Redis Mock으로 Kill Switch/Cooldown 상태 제어.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.risk.engine import RiskEngine
from agents.risk.models import (
    AccountState,
    HaltState,
    OpenPosition,
    RawSignal,
    UserContext,
    ValidationResult,
)


def _make_signal(**kwargs) -> RawSignal:
    defaults = dict(
        direction="LONG",
        coin="BTC",
        symbol="BTCUSDT",
        confidence=0.87,
        entry_price=Decimal("67450"),
        take_profit=Decimal("69200"),
        stop_loss=Decimal("66800"),
        leverage=5,
    )
    defaults.update(kwargs)
    return RawSignal(**defaults)


def _make_ctx(**kwargs) -> UserContext:
    defaults = dict(
        user_id=uuid.uuid4(),
        plan="pro",
        risk_profile="moderate",
        risk_per_trade=0.02,
        max_leverage=10,
        max_concurrent_positions=5,
        daily_loss_limit_pct=0.03,
        is_trading_active=True,
        allowed_hours_start=None,
        allowed_hours_end=None,
    )
    defaults.update(kwargs)
    return UserContext(**defaults)


def _make_account(**kwargs) -> AccountState:
    defaults = dict(
        available_balance=Decimal("10000"),
        total_balance=Decimal("10000"),
        initial_balance=Decimal("10000"),
        open_positions_count=0,
        open_positions_risk_usdt=Decimal("0"),
    )
    defaults.update(kwargs)
    return AccountState(**defaults)


@pytest.fixture
def mock_redis_clean():
    """Kill Switch/Cooldown 없는 클린 Redis Mock."""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=False)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def engine(mock_redis_clean):
    return RiskEngine(mock_redis_clean)


# ════════════════════════════════════════════════════════════════
# 전체 파이프라인 통과 테스트
# ════════════════════════════════════════════════════════════════

class TestFullPipelineApproval:
    async def test_valid_signal_approved(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is True
        assert result.quantity is not None and result.quantity > 0
        assert result.final_leverage is not None
        assert result.max_loss_usdt is not None

    async def test_approved_result_has_correct_leverage(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(leverage=15),  # AI 추천 15x
            ctx=_make_ctx(max_leverage=10),    # 사용자 max 10x
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is True
        # Pro 플랜 max 10x, 사용자 max 10x → 10x
        assert result.final_leverage == 10
        assert "LEVERAGE_CAPPED" in (result.warnings or [])


# ════════════════════════════════════════════════════════════════
# Kill Switch 테스트
# ════════════════════════════════════════════════════════════════

class TestKillSwitch:
    async def test_global_kill_switch_blocks_all(self, mock_redis_clean: AsyncMock) -> None:
        mock_redis_clean.exists = AsyncMock(return_value=True)   # global kill switch 활성
        engine = RiskEngine(mock_redis_clean)

        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert "KILL_SWITCH" in result.rejection_code

    async def test_halt_state_blocks_trading(self, mock_redis_clean: AsyncMock) -> None:
        import json
        halt_data = json.dumps({"trigger": "DAILY_LOSS_LIMIT", "until": "manual_resume"})

        def exists_side_effect(key):
            return AsyncMock(return_value=False)() if "global" in key else AsyncMock(return_value=False)()

        mock_redis_clean.exists = AsyncMock(return_value=False)
        mock_redis_clean.get = AsyncMock(return_value=halt_data)
        engine = RiskEngine(mock_redis_clean)

        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False


# ════════════════════════════════════════════════════════════════
# 개별 검증 체크 테스트
# ════════════════════════════════════════════════════════════════

class TestHoldSignal:
    async def test_hold_signal_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(direction="HOLD"),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "HOLD"


class TestTradingInactive:
    async def test_inactive_trading_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(is_trading_active=False),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "TRADING_INACTIVE"


class TestStopLossCheck:
    async def test_no_stop_loss_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(stop_loss=None),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "ORDER_003"


class TestRRRatioCheck:
    async def test_low_rr_ratio_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(
                take_profit=Decimal("68100"),  # R:R ≈ 1.0 < 2.0
                stop_loss=Decimal("66800"),
            ),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "ORDER_004"


class TestConfidenceCheck:
    async def test_low_confidence_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(confidence=0.55),  # < 60%
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "LOW_CONFIDENCE"


class TestDailyLossLimit:
    async def test_daily_loss_limit_reached_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(daily_loss_limit_pct=0.03),  # 3% = $300
            account=_make_account(total_balance=Decimal("10000")),
            daily_loss_usdt=Decimal("305"),            # 이미 한도 초과
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "ORDER_001"

    async def test_daily_loss_warning_still_approves(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(daily_loss_limit_pct=0.03),  # 3% = $300
            account=_make_account(total_balance=Decimal("10000")),
            daily_loss_usdt=Decimal("160"),            # 53% → 경고만
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is True
        assert any("DAILY_LOSS" in w for w in (result.warnings or []))


class TestConsecutiveLossCheck:
    async def test_5_consecutive_losses_rejected(
        self, mock_redis_clean: AsyncMock
    ) -> None:
        mock_redis_clean.exists = AsyncMock(return_value=False)
        mock_redis_clean.get = AsyncMock(return_value=None)
        engine = RiskEngine(mock_redis_clean)

        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=5,              # 5연속 → 중단
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "CONSEC_LOSS"


class TestPositionLimitCheck:
    async def test_position_limit_exceeded_rejected(self, engine: RiskEngine) -> None:
        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(plan="free", max_concurrent_positions=1),
            account=_make_account(open_positions_count=1),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=1,            # Free plan max 1개 → 초과
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "ORDER_002"


class TestSameCoinPosition:
    async def test_same_direction_triggers_dca(self, engine: RiskEngine) -> None:
        existing = OpenPosition(
            id=uuid.uuid4(),
            coin="BTC",
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=Decimal("65000"),
            quantity=Decimal("0.01"),
            stop_loss=Decimal("64000"),
            leverage=5,
        )
        result = await engine.validate(
            signal=_make_signal(direction="LONG"),
            ctx=_make_ctx(plan="pro"),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=1,
            same_coin_position=existing,
        )
        # DCA 경로 → 승인되어야 함 (포지션 한도가 1이어도 same coin이라면)
        assert result.pre_action == "dca"

    async def test_opposite_direction_triggers_close_existing(
        self, engine: RiskEngine
    ) -> None:
        existing = OpenPosition(
            id=uuid.uuid4(),
            coin="BTC",
            symbol="BTCUSDT",
            direction="SHORT",
            entry_price=Decimal("68000"),
            quantity=Decimal("0.01"),
            stop_loss=Decimal("69000"),
            leverage=5,
        )
        result = await engine.validate(
            signal=_make_signal(direction="LONG"),
            ctx=_make_ctx(plan="pro"),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=1,
            same_coin_position=existing,
        )
        assert result.pre_action == "close_existing"
        assert result.existing_position_id == existing.id


class TestSystemError:
    async def test_exception_returns_system_error(self, mock_redis_clean: AsyncMock) -> None:
        mock_redis_clean.exists = AsyncMock(side_effect=Exception("Redis error"))
        engine = RiskEngine(mock_redis_clean)

        result = await engine.validate(
            signal=_make_signal(),
            ctx=_make_ctx(),
            account=_make_account(),
            daily_loss_usdt=Decimal("0"),
            weekly_loss_usdt=Decimal("0"),
            weekly_limit_usdt=Decimal("1000"),
            consecutive_losses=0,
            open_positions_count=0,
            same_coin_position=None,
        )
        assert result.approved is False
        assert result.rejection_code == "SYSTEM_ERROR"
