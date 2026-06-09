"""
Prometheus 메트릭 레지스트리.

모든 메트릭은 이 모듈에서 정의한다.
다른 모듈은 이 모듈의 record_* 함수만 호출한다.

메트릭 네이밍: trading_<domain>_<measurement>_<unit>
"""
from __future__ import annotations

import time
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram, REGISTRY  # noqa: F401

# ── Agent Health ────────────────────────────────────────────────────────────────
AGENT_RUNS = Counter(
    "trading_agent_runs_total",
    "AI agent pipeline 실행 횟수",
    ["agent", "status"],          # agent: technical|sentiment|market|synthesis|risk_manager
)                                 # status: success|failure

AGENT_DURATION = Histogram(
    "trading_agent_duration_seconds",
    "AI agent pipeline 처리 시간",
    ["agent"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

AGENT_LAST_RUN = Gauge(
    "trading_agent_last_run_timestamp_seconds",
    "마지막 agent 실행 Unix timestamp",
    ["agent"],
)

# ── Queue Health ────────────────────────────────────────────────────────────────
CELERY_TASKS = Counter(
    "trading_celery_tasks_total",
    "Celery 태스크 완료 횟수",
    ["task_name", "status"],      # status: success|failure|retry
)

CELERY_TASK_DURATION = Histogram(
    "trading_celery_task_duration_seconds",
    "Celery 태스크 처리 시간",
    ["task_name"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

CELERY_QUEUE_LENGTH = Gauge(
    "trading_celery_queue_length",
    "Celery 큐 대기 태스크 수",
    ["queue"],
)

# ── Order Execution ─────────────────────────────────────────────────────────────
ORDERS_TOTAL = Counter(
    "trading_orders_total",
    "주문 실행 횟수",
    ["symbol", "side", "status"],  # status: filled|rejected|error
)

ORDER_LATENCY = Histogram(
    "trading_order_latency_seconds",
    "주문 API 응답 시간",
    ["symbol"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

ORDER_SL_PLACED = Counter(
    "trading_order_sl_placed_total",
    "SL 주문 설정 횟수 (진입 후 SL 주문 성공/실패)",
    ["symbol", "status"],
)

# ── Daily PnL ───────────────────────────────────────────────────────────────────
DAILY_PNL_USDT = Gauge(
    "trading_daily_pnl_usdt",
    "사용자별 당일 누적 PnL (USDT)",
    ["user_id"],
)

TRADE_PNL = Histogram(
    "trading_trade_pnl_usdt",
    "거래별 PnL 분포 (USDT)",
    ["symbol", "direction"],
    buckets=[-1000.0, -500.0, -200.0, -100.0, -50.0, 0.0, 50.0, 100.0, 200.0, 500.0, 1000.0],
)

SIGNALS_GENERATED = Counter(
    "trading_signals_total",
    "시그널 생성 횟수",
    ["symbol", "direction"],      # direction: LONG|SHORT|HOLD
)

SIGNALS_EXECUTED = Counter(
    "trading_signals_executed_total",
    "실행된 시그널 횟수",
    ["symbol", "direction"],
)

# ── Drawdown ────────────────────────────────────────────────────────────────────
DRAWDOWN_PCT = Gauge(
    "trading_drawdown_pct",
    "현재 드로우다운 비율 (0.0 ~ 1.0, 1.0 = 100%)",
    ["user_id"],
)

PEAK_BALANCE_USDT = Gauge(
    "trading_peak_balance_usdt",
    "피크 잔고 (USDT)",
    ["user_id"],
)

CURRENT_BALANCE_USDT = Gauge(
    "trading_current_balance_usdt",
    "현재 잔고 (USDT)",
    ["user_id"],
)

# ── Safety Halt ─────────────────────────────────────────────────────────────────
SAFETY_HALT_ACTIVE = Gauge(
    "trading_safety_halt_active",
    "Safety halt 활성 여부 (1=정지, 0=정상)",
    ["scope", "reason"],          # scope: user:<id>|global
)

SAFETY_GATE_CHECKS = Counter(
    "trading_safety_gate_checks_total",
    "Safety Gate 검사 횟수",
    ["result"],                   # result: allowed|blocked
)

SAFETY_GATE_BLOCK_REASON = Counter(
    "trading_safety_gate_blocks_total",
    "Safety Gate 차단 사유별 횟수",
    ["reason"],
)

# ── Error Rate ──────────────────────────────────────────────────────────────────
ERRORS_TOTAL = Counter(
    "trading_errors_total",
    "애플리케이션 오류 횟수",
    ["component", "error_type"],
)

# ── HTTP Metrics ─────────────────────────────────────────────────────────────────
HTTP_REQUESTS = Counter(
    "trading_http_requests_total",
    "HTTP 요청 횟수",
    ["method", "path", "status"],
)

HTTP_DURATION = Histogram(
    "trading_http_request_duration_seconds",
    "HTTP 요청 처리 시간",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


# ── Record Helpers ──────────────────────────────────────────────────────────────
# 다른 모듈은 이 함수들을 통해서만 메트릭을 기록한다.

def record_agent_run(
    agent: str,
    status: Literal["success", "failure"],
    duration_seconds: float,
) -> None:
    AGENT_RUNS.labels(agent=agent, status=status).inc()
    AGENT_DURATION.labels(agent=agent).observe(duration_seconds)
    if status == "success":
        AGENT_LAST_RUN.labels(agent=agent).set(time.time())


def record_order(
    symbol: str,
    side: str,
    status: Literal["filled", "rejected", "error"],
    latency_seconds: float,
) -> None:
    ORDERS_TOTAL.labels(symbol=symbol, side=side.upper(), status=status).inc()
    ORDER_LATENCY.labels(symbol=symbol).observe(latency_seconds)


def record_sl_placed(symbol: str, success: bool) -> None:
    ORDER_SL_PLACED.labels(symbol=symbol, status="success" if success else "failure").inc()


def record_trade_closed(
    user_id: str,
    symbol: str,
    direction: str,
    pnl_usdt: float,
    daily_pnl_cumulative: float,
) -> None:
    TRADE_PNL.labels(symbol=symbol, direction=direction.upper()).observe(pnl_usdt)
    DAILY_PNL_USDT.labels(user_id=user_id).set(daily_pnl_cumulative)


def record_balance(user_id: str, current: float, peak: float) -> None:
    CURRENT_BALANCE_USDT.labels(user_id=user_id).set(current)
    PEAK_BALANCE_USDT.labels(user_id=user_id).set(peak)
    drawdown = (peak - current) / peak if peak > 0 else 0.0
    DRAWDOWN_PCT.labels(user_id=user_id).set(max(0.0, drawdown))


def record_safety_gate(
    allowed: bool,
    halt_reason: str | None = None,
) -> None:
    SAFETY_GATE_CHECKS.labels(result="allowed" if allowed else "blocked").inc()
    if not allowed and halt_reason:
        SAFETY_GATE_BLOCK_REASON.labels(reason=halt_reason).inc()


def record_safety_halt(scope: str, reason: str, active: bool) -> None:
    SAFETY_HALT_ACTIVE.labels(scope=scope, reason=reason).set(1 if active else 0)


def record_error(component: str, error_type: str) -> None:
    ERRORS_TOTAL.labels(component=component, error_type=error_type).inc()


def record_signal(symbol: str, direction: str) -> None:
    SIGNALS_GENERATED.labels(symbol=symbol, direction=direction.upper()).inc()


def record_celery_task(
    task_name: str,
    status: Literal["success", "failure", "retry"],
    duration_seconds: float,
) -> None:
    short_name = task_name.split(".")[-1]
    CELERY_TASKS.labels(task_name=short_name, status=status).inc()
    CELERY_TASK_DURATION.labels(task_name=short_name).observe(duration_seconds)
