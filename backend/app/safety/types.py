"""
Live Trading Safety Layer — 타입 정의.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from . import constants


class HaltReason(str, Enum):
    LIVE_TRADING_DISABLED     = "LIVE_TRADING_DISABLED"
    DAILY_LOSS_LIMIT          = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT         = "WEEKLY_LOSS_LIMIT"
    DRAWDOWN_PROTECTION       = "DRAWDOWN_PROTECTION"
    EMERGENCY_SHUTDOWN        = "EMERGENCY_SHUTDOWN"
    CONSECUTIVE_API_FAILURES  = "CONSECUTIVE_API_FAILURES"


class AlertLevel(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


@dataclass
class SafetyConfig:
    live_trading_enabled: bool = constants.LIVE_TRADING_ENABLED_DEFAULT

    # Daily kill switch
    daily_loss_limit_pct: float = constants.DAILY_LOSS_LIMIT_DEFAULTS["moderate"]

    # Weekly kill switch
    weekly_loss_limit_pct: float = constants.WEEKLY_LOSS_LIMIT_DEFAULTS["moderate"]

    # Drawdown protection
    drawdown_warning_pct: float = constants.DRAWDOWN_WARNING_PCT
    drawdown_halt_pct: float    = constants.DRAWDOWN_HALT_PCT

    # Exchange disconnect protection
    api_failure_halt_threshold: int    = constants.API_FAILURE_HALT_THRESHOLD
    api_failure_halt_minutes: int      = constants.API_FAILURE_HALT_MINUTES


@dataclass
class SafetyCheckResult:
    allowed:     bool
    halt_reason: Optional[HaltReason] = None
    message:     str = ""
    alert_level: AlertLevel = AlertLevel.INFO


@dataclass
class KillSwitchState:
    user_id:              str
    is_halted:            bool             = False
    halt_reason:          Optional[HaltReason] = None
    halt_until:           Optional[datetime]   = None
    current_loss_usdt:    float            = 0.0
    period_start_balance: float            = 0.0


@dataclass
class DisconnectState:
    consecutive_failures: int              = 0
    last_failure_at:      Optional[datetime] = None
    halt_until:           Optional[datetime] = None
    is_halted:            bool             = False


@dataclass
class EmergencyState:
    is_active:             bool             = False
    activated_at:          Optional[datetime] = None
    activated_by:          Optional[str]    = None   # "user" | "system"
    reason:                str             = ""
    requires_manual_resume: bool           = True


@dataclass
class DrawdownState:
    peak_balance:    float = 0.0
    current_balance: float = 0.0
    is_halted:       bool  = False
    warning_sent:    bool  = False
