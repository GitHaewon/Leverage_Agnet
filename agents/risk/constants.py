"""
Risk Agent 상수 — TRADING_RULES.md §11.3과 1:1 대응.

이 파일의 값을 변경하려면 반드시 TRADING_RULES.md를 먼저 업데이트해야 한다.
어떤 규칙도 개별 사용자 요청으로 우회할 수 없다.
"""
from __future__ import annotations

# ── 레버리지 (§1) ───────────────────────────────────────────────────────────────
SYSTEM_MAX_LEVERAGE: int = 20
ABSOLUTE_MIN_LEVERAGE: int = 1

PLAN_MAX_LEVERAGE: dict[str, int] = {
    "free":  5,
    "pro":  10,
    "elite": 20,
}

RISK_PROFILE_DEFAULT_LEVERAGE: dict[str, int] = {
    "conservative": 3,
    "moderate":     5,
    "aggressive":  10,
}

LEVERAGE_WARNING_THRESHOLDS: dict[str, int] = {
    "conservative":  5,
    "moderate":     10,
    "aggressive":   15,
}

# ── 포지션 수 (§2) ─────────────────────────────────────────────────────────────
PLAN_MAX_POSITIONS: dict[str, int] = {
    "free":  1,
    "pro":   5,
    "elite": 20,
}
MAX_POSITIONS_PER_COIN: int = 1

# ── 계좌 위험 (§3) ─────────────────────────────────────────────────────────────
RISK_PER_TRADE_MIN: float = 0.005     # 0.5%
RISK_PER_TRADE_MAX: float = 0.050     # 5.0%

RISK_PROFILE_DEFAULT_RISK: dict[str, float] = {
    "conservative": 0.01,
    "moderate":     0.02,
    "aggressive":   0.03,
}

MAX_PORTFOLIO_RISK: float = 0.10              # 10%
MAX_PORTFOLIO_RISK_AGGRESSIVE: float = 0.15  # 15%
MAX_SINGLE_POSITION_MARGIN_RATIO: float = 0.20  # 20%
MARGIN_BUFFER_RATIO: float = 1.10            # 10% 버퍼

# ── 일일 손실 (§4) ─────────────────────────────────────────────────────────────
DAILY_LOSS_LIMIT_MIN: float = 0.005    # 0.5%
DAILY_LOSS_LIMIT_MAX: float = 0.100   # 10.0%

DAILY_LOSS_LIMIT_DEFAULTS: dict[str, float] = {
    "conservative": 0.02,
    "moderate":     0.03,
    "aggressive":   0.05,
}

DAILY_LOSS_WARNING_PCT: float = 0.50   # 50% 도달 시 경고
DAILY_LOSS_CAUTION_PCT: float = 0.80   # 80% 도달 시 주의
DAILY_LOSS_HALT_PCT: float    = 1.00   # 100% 도달 시 중단
DAILY_LOSS_RESET_HOUR_UTC: int = 0     # 자정 UTC

# ── 주간 손실 (§5) ─────────────────────────────────────────────────────────────
WEEKLY_LOSS_LIMIT_DEFAULTS: dict[str, float] = {
    "conservative": 0.05,
    "moderate":     0.10,
    "aggressive":   0.15,
}
WEEKLY_LOSS_RESET_DAY: int = 0         # 월요일

WEEKLY_LOSS_WARNING_PCT: float = 0.50
WEEKLY_LOSS_CAUTION_PCT: float = 0.75
WEEKLY_LOSS_SEMI_AUTO_PCT: float = 0.90  # 반자동 강제 전환
WEEKLY_LOSS_HALT_PCT: float = 1.00

# ── 연속 손실 (§6) ─────────────────────────────────────────────────────────────
CONSECUTIVE_LOSS_COOLDOWN: int = 3    # 3연속 → 30분 쿨다운
CONSECUTIVE_LOSS_HALT: int    = 5    # 5연속 → 자동매매 중단
COOLDOWN_MINUTES: int         = 30

CONSECUTIVE_LOSS_AUTO_RESUME: bool = True   # 쿨다운은 자동 해제
HALT_REQUIRES_MANUAL_RESUME: bool  = True   # 5연속 손실은 수동 재활성화

# ── 포지션 사이징 (§7) ─────────────────────────────────────────────────────────
MIN_RR_RATIO: float    = 2.0
MIN_CONFIDENCE: float  = 0.60

BINANCE_LOT_SIZES: dict[str, float] = {
    "BTCUSDT": 0.001,
    "ETHUSDT": 0.01,
    "DEFAULT": 0.001,
}

BINANCE_MIN_NOTIONAL: dict[str, float] = {
    "BTCUSDT": 5.0,
    "ETHUSDT": 5.0,
    "DEFAULT": 5.0,
}

# ── DCA (§8) ───────────────────────────────────────────────────────────────────
DCA_ENABLED: bool          = True
MAX_DCA_COUNT: int         = 2
DCA_RISK_MULTIPLIER: float = 2.0
DCA_MIN_PRICE_MOVE_ATR: float = 1.0

# ── 긴급 청산 (§10) ────────────────────────────────────────────────────────────
LIQ_DISTANCE_WARNING: float = 0.10   # 10% 이내 → 경보
LIQ_DISTANCE_PARTIAL: float = 0.03   # 3% 이내 → 50% 청산
LIQ_DISTANCE_FULL: float    = 0.02   # 2% 이내 → 100% 청산
PARTIAL_CLOSE_RATIO: float  = 0.50

ACCOUNT_EMERGENCY_THRESHOLD: float  = 0.10  # 초기 잔고의 10%
CLOSEALL_TIMEOUT_SECONDS: int       = 10
CLOSEALL_CONFIRMATION_KEYWORD: str  = "CLOSE_ALL"

# ── Redis 키 (Kill Switch / Halt) ──────────────────────────────────────────────
REDIS_KEY_GLOBAL_KILL_SWITCH: str   = "risk:kill_switch:global"
REDIS_KEY_USER_KILL_SWITCH: str     = "risk:kill_switch:{user_id}"
REDIS_KEY_USER_HALT: str            = "risk:halt:{user_id}"
REDIS_KEY_USER_COOLDOWN: str        = "risk:cooldown:{user_id}"
REDIS_KEY_DAILY_LOSS: str           = "risk:daily_loss:{user_id}:{date}"

# ── AI 신뢰도별 추천 레버리지 (§1.4) ──────────────────────────────────────────
_CONFIDENCE_LEVERAGE_MAP: list[tuple[float, int]] = [
    (0.95, 15),
    (0.90, 10),
    (0.80,  7),
    (0.70,  5),
    (0.60,  3),
]


def get_ai_recommended_leverage(confidence: float) -> int:
    """신뢰도에 따른 AI 추천 레버리지 (§1.4)."""
    if confidence < MIN_CONFIDENCE:
        raise ValueError(f"confidence {confidence:.0%} < {MIN_CONFIDENCE:.0%} — should not reach here")
    for threshold, leverage in _CONFIDENCE_LEVERAGE_MAP:
        if confidence >= threshold:
            return leverage
    return 3
