# Pre-Live Trading Checklist

> Updated: 2026-06-12

**This system is not guaranteed to be profitable. Cryptocurrency futures trading carries significant risk of total loss. Complete every item below before enabling live trading.**

---

## Environment

- [ ] `BINANCE_TESTNET=false` — only after all other items are done
- [ ] `LIVE_TRADING_ENABLED=true` — flip this last, in production only
- [ ] `SHADOW_TRADING_ENABLED=false` — shadow and live are mutually exclusive
- [ ] `OPENAI_API_KEY` is set and valid (not empty, not expired)
- [ ] `OPENAI_MODEL=gpt-5` (or confirmed working model via `scripts/verify_openai.py`)
- [ ] `BINANCE_ENCRYPT_KEY` is a 32-byte hex string generated with `secrets.token_hex(32)`
- [ ] `JWT_SECRET` and `JWT_REFRESH_SECRET` are unique 32+ character random strings
- [ ] `.env` is not committed to git (check `.gitignore`)

---

## Binance API key

- [ ] API key has **Read** and **Trade** permissions only
- [ ] API key does **not** have Withdrawal permission (system rejects it, but verify manually)
- [ ] API key is registered for Binance **Futures** (USDT-M), not spot
- [ ] API key IP whitelist is configured if your deployment has a static IP
- [ ] Key can be verified: `scripts/verify_openai.py` or equivalent Binance test call

---

## Shadow trading period

- [ ] Shadow mode ran for **at least 2 weeks** of real market data
- [ ] At least **30 shadow trades** were executed (not just evaluated)
- [ ] Win rate ≥ 45% (review `shadow_performance_summary.json`)
- [ ] Average realised R:R ≥ 1.5
- [ ] HOLD rate is not suspiciously high (> 95% may indicate misconfiguration)
- [ ] AI REJECT rate is reasonable (< 70%)
- [ ] Emergency close path was tested at least once (via testnet)
- [ ] Decision logs look correct (`event=decision_log` entries in app log)

---

## Risk settings (user account)

- [ ] `risk_per_trade_pct` is set to a value you can afford to lose per trade
- [ ] `daily_loss_limit` is set (recommended: ≤ 3% of account)
- [ ] `max_leverage` is set to ≤ 10x for conservative operation
- [ ] `max_concurrent_positions` is 1 for MVP
- [ ] Telegram alerts are configured and a test message was received

---

## System health

- [ ] `GET /health/detailed` returns all checks `ok`
- [ ] PostgreSQL connection is stable
- [ ] Redis connection is stable
- [ ] Celery workers are running (`worker-analysis`, `worker-order`, `worker-notification`)
- [ ] Celery Beat is running (5-minute analysis cycle)
- [ ] Grafana / Prometheus are accessible for monitoring

---

## Code and tests

- [ ] All unit tests pass: `pytest backend/tests/unit/agents/ --tb=short`
- [ ] Order execution path coverage ≥ 95%
- [ ] No open PR with changes to `agents/risk/`, `agents/execution/`, or `agents/orchestrator/pipeline.py`
- [ ] `agents/analyst/` is not wired to the production pipeline (it is deprecated)

---

## Emergency procedures

- [ ] You know how to trigger the kill switch via the dashboard
- [ ] You know how to set `LIVE_TRADING_ENABLED=false` and restart workers quickly
- [ ] Telegram emergency stop alert has been tested
- [ ] You have a plan for what to do if a position is opened but TP/SL fails (the system handles this automatically, but confirm the emergency close path in logs)

---

## Final gate

Before flipping `LIVE_TRADING_ENABLED=true`:

```bash
# Verify the pipeline produces correct FinalDecision objects
# by running a single dry-run cycle against testnet data:
python -m backend.scripts.dry_run_pipeline --coin BTC --shadow
```

If this prints a `FinalDecision(action=HOLD)` or `FinalDecision(action=LONG/SHORT)` with all fields populated correctly, the system is ready.
