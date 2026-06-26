# Shadow Trading

> Updated: 2026-06-12
> Source: `agents/shadow/`, `scripts/analyze_shadow_performance.py`

---

## What shadow trading does

Shadow trading runs the **complete 10-step pipeline** — market data, technical analysis, decision engine, AI review, risk validation, final decision — using real market data. The only difference is Step 10: instead of placing a real Binance order, `ShadowExecutionEngine` creates a virtual fill and stores a `ShadowTradeRecord`.

**No real orders are ever placed in shadow mode.** `ShadowExecutionEngine` holds no Binance gateway reference.

---

## Enable shadow mode

In `.env`:

```bash
SHADOW_TRADING_ENABLED=true
LIVE_TRADING_ENABLED=false   # must stay false during shadow period
BINANCE_TESTNET=true         # use testnet for market data during development
```

In `backend/app/workers/analysis_worker.py`, wire `OrchestratorDeps.execution` to `ShadowExecutionEngine` instead of the real `ExecutionEngine`.

---

## ShadowExecutionEngine behaviour

`agents/shadow/execution.py`

1. Accepts `ExecutionRequest` with `approved_validation`, `final_decision`, and `candidate` populated.
2. Verifies `FinalDecision` is present and action is `LONG` or `SHORT`.
3. Verifies `stop_loss` and `take_profit` are present.
4. Creates a virtual `FilledOrder` at `entry_price` (immediate fill assumption — no slippage in shadow).
5. Saves `ShadowTradeRecord` via `ShadowTradeStoreProtocol`.
6. Returns `ExecutionResult(mode="paper", approved=True, executed=True)`.

Any exception → `ExecutionResult(mode="paper", approved=False, rejection_code="SYSTEM_ERROR")`.

---

## ShadowTradeRecord

`agents/shadow/models.py`

| Field | Description |
|---|---|
| `id` | UUID |
| `user_id` | Owner |
| `coin` / `symbol` | e.g. `BTC` / `BTCUSDT` |
| `direction` | `LONG` or `SHORT` |
| `entry_price` | Virtual fill price |
| `tp_price` / `sl_price` | Target and stop |
| `quantity` | From `ValidationResult.quantity` |
| `leverage` | From `ValidationResult.final_leverage` |
| `opened_at` | Timestamp |
| `closed_at` | Populated when the shadow trade is closed |
| `close_price` | Actual close price |
| `realized_pnl` | Gross P&L (pre-fee estimate) |
| `close_reason` | `tp_hit` / `sl_hit` / `manual` |

---

## Decision logs

Every pipeline run (HOLD or execute) emits a structured `decision_log` JSON entry. These are the primary input to shadow performance analysis. Each entry includes regime, all scores, strategy type, R:R, cost estimates, AI review outcome, risk outcome, and final action.

Log output location: application log stream (default `stdout`) tagged with `event=decision_log`.

---

## Running shadow performance analysis

```bash
# Collect decision logs from your log file or stdout redirect
python scripts/analyze_shadow_performance.py <path/to/app.log>

# Specify a different output file (default: shadow_performance_summary.json)
python scripts/analyze_shadow_performance.py <path/to/app.log> -o my_summary.json
```

The script reads JSONL-formatted `decision_log` entries, computes aggregate metrics, prints a human-readable summary, and writes a machine-readable JSON file.

## Running shadow DB quality analysis

Use this when the Docker/Celery pipeline is writing `shadow_decisions` directly
to Postgres and you want a pre-live quality check before any real trading:

```bash
python scripts/analyze_shadow_db.py
python scripts/analyze_shadow_db.py -o logs/shadow_db_summary.json
```

The script reads `DATABASE_URL` first, or `POSTGRES_USER`,
`POSTGRES_PASSWORD`, and `POSTGRES_DB` from `backend/.env`, root `.env`, or the
process environment. If `shadow_trades` is empty, it prints `성과 판단 불가`
because win rate and PnL cannot be evaluated yet.

## Shadow-only threshold experiments

Shadow mode can use relaxed DecisionEngine gates without changing live trading
defaults:

```bash
SHADOW_MIN_LONG_SCORE=60
SHADOW_MIN_SHORT_SCORE=60
SHADOW_MAX_RISK_SCORE=70
```

These values are read only when `SHADOW_TRADING_ENABLED=true` and
`LIVE_TRADING_ENABLED=false`. If an env var is omitted, the existing conservative
DecisionEngine defaults remain in effect: long `75.0`, short `75.0`, risk `55.0`.

For the standalone live-data shadow runner, use the same env vars or one-off CLI
overrides:

```bash
python scripts/run_shadow_live.py --symbol BTCUSDT \
  --shadow-min-long-score 60 \
  --shadow-min-short-score 60 \
  --shadow-max-risk-score 70
```

Every new `shadow_decisions` row stores the applied `min_long_score`,
`min_short_score`, and `max_risk_score`, plus the observed `long_score`,
`short_score`, `risk_score`, and `decision_score_summary`. Use
`scripts/analyze_shadow_db.py` to compare score distributions against the active
thresholds.

## One-shot local smoke test

Run a single local shadow decision without Binance order permissions, secrets, Redis,
or database setup:

```bash
.venv/bin/python scripts/run_shadow_smoke.py --symbol BTCUSDT
```

The smoke runner refuses to start when `LIVE_TRADING_ENABLED=true`. By default it
uses deterministic fake market data and a fake AI reviewer fixture, then runs the
deterministic `DecisionEngine`, real `RiskEngine.validate_candidate`,
`decide_final_action`, and `ShadowExecutionEngine` with an in-memory store. It
writes JSONL output to:

```bash
logs/shadow_smoke_decisions.jsonl
```

Analyze the generated log with:

```bash
.venv/bin/python scripts/analyze_shadow_performance.py logs/shadow_smoke_decisions.jsonl
```

To append deterministic closed sample rows for analyzer verification, add:

```bash
.venv/bin/python scripts/run_shadow_smoke.py --symbol BTCUSDT --include-closed-samples
```

This writes one winning LONG, one losing LONG, one winning SHORT, and one HOLD
rejection after the normal smoke decision. The sample rows are JSONL fixtures
only; they do not place orders or call exchange APIs.

To explicitly call the real AI reviewer, pass `--use-real-ai` and ensure
`OPENAI_API_KEY` is set:

```bash
.venv/bin/python scripts/run_shadow_smoke.py --symbol BTCUSDT --use-real-ai
```

**Metrics computed:**

- Total signals evaluated, HOLD rate, execution rate
- Win rate, average R:R (realised), average hold time
- Breakdown by strategy type
- Rejection breakdown by stage (decision / AI / risk / final)
- AI confidence distribution
- Regime breakdown

---

## Interpreting results before going live

| Metric | Minimum recommendation |
|---|---|
| Shadow period | ≥ 2 weeks of real market data |
| Minimum trades executed | ≥ 30 |
| Win rate (shadow) | ≥ 45% (highly strategy-dependent) |
| Average R:R realised | ≥ 1.5 |
| HOLD rate | Check that it is not ≥ 95% (thresholds may be too tight) |
| AI REJECT rate | Check if consistently > 70% (AI may need prompt review) |

If HOLD rate is very high, examine the decision log breakdown to identify which stage is filtering most aggressively, then tune the relevant constants in `agents/decision/constants.py`.

---

## Transitioning to live trading

See `docs/LIVE_TRADING_CHECKLIST.md`.
