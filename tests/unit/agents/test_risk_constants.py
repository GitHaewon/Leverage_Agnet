"""
Risk 상수가 TRADING_RULES.md §11.3과 정확히 일치하는지 검증.
이 테스트가 실패하면 상수 파일과 문서가 불일치 상태.
"""
from __future__ import annotations

from agents.risk.constants import (
    ACCOUNT_EMERGENCY_THRESHOLD,
    BINANCE_LOT_SIZES,
    BINANCE_MIN_NOTIONAL,
    CLOSEALL_CONFIRMATION_KEYWORD,
    CLOSEALL_TIMEOUT_SECONDS,
    CONSECUTIVE_LOSS_COOLDOWN,
    CONSECUTIVE_LOSS_HALT,
    COOLDOWN_MINUTES,
    DAILY_LOSS_CAUTION_PCT,
    DAILY_LOSS_HALT_PCT,
    DAILY_LOSS_LIMIT_DEFAULTS,
    DAILY_LOSS_WARNING_PCT,
    DCA_RISK_MULTIPLIER,
    LIQ_DISTANCE_FULL,
    LIQ_DISTANCE_PARTIAL,
    LIQ_DISTANCE_WARNING,
    MAX_DCA_COUNT,
    MAX_PORTFOLIO_RISK,
    MAX_PORTFOLIO_RISK_AGGRESSIVE,
    MAX_SINGLE_POSITION_MARGIN_RATIO,
    MIN_CONFIDENCE,
    MIN_RR_RATIO,
    PARTIAL_CLOSE_RATIO,
    PLAN_MAX_LEVERAGE,
    PLAN_MAX_POSITIONS,
    RISK_PER_TRADE_MAX,
    RISK_PER_TRADE_MIN,
    SYSTEM_MAX_LEVERAGE,
    WEEKLY_LOSS_LIMIT_DEFAULTS,
    get_ai_recommended_leverage,
)


class TestLeverageConstants:
    def test_system_max_leverage(self) -> None:
        assert SYSTEM_MAX_LEVERAGE == 20

    def test_plan_max_leverage(self) -> None:
        assert PLAN_MAX_LEVERAGE["free"] == 5
        assert PLAN_MAX_LEVERAGE["pro"] == 10
        assert PLAN_MAX_LEVERAGE["elite"] == 20

    def test_ai_leverage_by_confidence(self) -> None:
        assert get_ai_recommended_leverage(0.60) == 3
        assert get_ai_recommended_leverage(0.69) == 3
        assert get_ai_recommended_leverage(0.70) == 5
        assert get_ai_recommended_leverage(0.79) == 5
        assert get_ai_recommended_leverage(0.80) == 7
        assert get_ai_recommended_leverage(0.89) == 7
        assert get_ai_recommended_leverage(0.90) == 10
        assert get_ai_recommended_leverage(0.94) == 10
        assert get_ai_recommended_leverage(0.95) == 15
        assert get_ai_recommended_leverage(1.00) == 15

    def test_ai_leverage_below_min_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            get_ai_recommended_leverage(0.59)


class TestPositionConstants:
    def test_plan_max_positions(self) -> None:
        assert PLAN_MAX_POSITIONS["free"] == 1
        assert PLAN_MAX_POSITIONS["pro"] == 5
        assert PLAN_MAX_POSITIONS["elite"] == 20


class TestRiskPerTradeConstants:
    def test_risk_per_trade_range(self) -> None:
        assert RISK_PER_TRADE_MIN == 0.005
        assert RISK_PER_TRADE_MAX == 0.050

    def test_portfolio_risk_limits(self) -> None:
        assert MAX_PORTFOLIO_RISK == 0.10
        assert MAX_PORTFOLIO_RISK_AGGRESSIVE == 0.15

    def test_margin_ratio(self) -> None:
        assert MAX_SINGLE_POSITION_MARGIN_RATIO == 0.20


class TestDailyLossConstants:
    def test_halt_percentage_is_100(self) -> None:
        assert DAILY_LOSS_HALT_PCT == 1.00

    def test_warning_thresholds(self) -> None:
        assert DAILY_LOSS_WARNING_PCT == 0.50
        assert DAILY_LOSS_CAUTION_PCT == 0.80
        assert DAILY_LOSS_HALT_PCT == 1.00

    def test_defaults_by_profile(self) -> None:
        assert DAILY_LOSS_LIMIT_DEFAULTS["conservative"] == 0.02
        assert DAILY_LOSS_LIMIT_DEFAULTS["moderate"] == 0.03
        assert DAILY_LOSS_LIMIT_DEFAULTS["aggressive"] == 0.05


class TestWeeklyLossConstants:
    def test_weekly_defaults(self) -> None:
        assert WEEKLY_LOSS_LIMIT_DEFAULTS["conservative"] == 0.05
        assert WEEKLY_LOSS_LIMIT_DEFAULTS["moderate"] == 0.10
        assert WEEKLY_LOSS_LIMIT_DEFAULTS["aggressive"] == 0.15


class TestConsecutiveLossConstants:
    def test_cooldown_at_3(self) -> None:
        assert CONSECUTIVE_LOSS_COOLDOWN == 3

    def test_halt_at_5(self) -> None:
        assert CONSECUTIVE_LOSS_HALT == 5

    def test_cooldown_duration(self) -> None:
        assert COOLDOWN_MINUTES == 30


class TestSizingConstants:
    def test_min_rr_ratio(self) -> None:
        assert MIN_RR_RATIO == 2.0

    def test_min_confidence(self) -> None:
        assert MIN_CONFIDENCE == 0.60

    def test_btc_lot_size(self) -> None:
        assert BINANCE_LOT_SIZES["BTCUSDT"] == 0.001

    def test_eth_lot_size(self) -> None:
        assert BINANCE_LOT_SIZES["ETHUSDT"] == 0.01

    def test_min_notional(self) -> None:
        assert BINANCE_MIN_NOTIONAL["BTCUSDT"] == 5.0


class TestDCAConstants:
    def test_max_dca_count(self) -> None:
        assert MAX_DCA_COUNT == 2

    def test_dca_risk_multiplier(self) -> None:
        assert DCA_RISK_MULTIPLIER == 2.0


class TestEmergencyConstants:
    def test_liquidation_thresholds(self) -> None:
        assert LIQ_DISTANCE_WARNING == 0.10
        assert LIQ_DISTANCE_PARTIAL == 0.03
        assert LIQ_DISTANCE_FULL == 0.02

    def test_partial_close_ratio(self) -> None:
        assert PARTIAL_CLOSE_RATIO == 0.50

    def test_account_emergency_threshold(self) -> None:
        assert ACCOUNT_EMERGENCY_THRESHOLD == 0.10

    def test_closeall_confirmation_keyword(self) -> None:
        assert CLOSEALL_CONFIRMATION_KEYWORD == "CLOSE_ALL"

    def test_closeall_timeout(self) -> None:
        assert CLOSEALL_TIMEOUT_SECONDS == 10
