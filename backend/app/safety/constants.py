"""
Live Trading Safety Layer — 상수 정의.

TRADING_RULES.md §4, §5, §9, §10 기준.
모든 임계값은 이 파일에서만 관리한다.
"""
from __future__ import annotations

# ── 마스터 스위치 ──────────────────────────────────────────────────────────────
LIVE_TRADING_ENABLED_DEFAULT: bool = False   # 반드시 False가 기본값

# ── 일일 손실 한도 (§4) ───────────────────────────────────────────────────────
DAILY_LOSS_WARNING_PCT: float = 0.50    # 한도 50% → 경고 알림
DAILY_LOSS_CAUTION_PCT: float = 0.80    # 한도 80% → 주의 알림
DAILY_LOSS_HALT_PCT: float = 1.00       # 한도 100% → 자동매매 중단
DAILY_LOSS_LIMIT_MIN: float = 0.005     # 최소 0.5%
DAILY_LOSS_LIMIT_MAX: float = 0.100     # 최대 10.0%
DAILY_LOSS_LIMIT_DEFAULTS: dict[str, float] = {
    "conservative": 0.02,
    "moderate":     0.03,
    "aggressive":   0.05,
}

# ── 주간 손실 한도 (§5) ───────────────────────────────────────────────────────
WEEKLY_LOSS_WARNING_PCT: float = 0.50   # 한도 50% → 경고
WEEKLY_LOSS_CAUTION_PCT: float = 0.75   # 한도 75% → 주의
WEEKLY_LOSS_HALT_PCT: float = 1.00      # 한도 100% → 주간 중단
WEEKLY_LOSS_LIMIT_DEFAULTS: dict[str, float] = {
    "conservative": 0.05,
    "moderate":     0.10,
    "aggressive":   0.15,
}

# ── 드로우다운 보호 ────────────────────────────────────────────────────────────
DRAWDOWN_WARNING_PCT: float = 0.10      # 고점 대비 10% 하락 → 경고
DRAWDOWN_HALT_PCT: float = 0.20         # 고점 대비 20% 하락 → 중단 (수동 재개)

# ── 거래소 연결 오류 보호 (§9.1 API_FAILURES) ─────────────────────────────────
API_FAILURE_HALT_THRESHOLD: int = 3     # 연속 3회 실패 → 중단
API_FAILURE_HALT_MINUTES: int = 30      # 30분 중단
