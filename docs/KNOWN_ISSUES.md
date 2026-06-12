# Known Issues

> Updated: 2026-06-12

These are confirmed pre-existing issues and documented design trade-offs. None of them affect the correctness of the production pipeline under normal conditions.

---

## Test environment

### 1. `celery` not installed — shadow monitor tests fail

**Affected:** `backend/tests/unit/test_shadow_execution.py` — `test_monitor_*` (3 tests)

`backend/app/workers/shadow_monitor_worker.py` imports `celery` at module level. When celery is not installed, the import fails and the test module cannot load.

**Impact:** Shadow monitor worker cannot be imported or tested without celery installed. The `ShadowExecutionEngine` itself (16 tests) is unaffected.

**Fix:** `pip install celery[redis]` in the test environment, or add celery to the dev dependencies in `pyproject.toml`.

---

### 2. `websockets` not installed — market data collection tests fail

**Affected:** 4 `test_market_data_*` tests

`agents/market_data/` uses the `websockets` library for Binance WebSocket streams. Tests fail when the library is not installed.

**Fix:** `pip install websockets` in the test environment.

---

### 3. `fakeredis` / numeric setup issues

**Affected:** `test_kill_switch`, `test_sizing_engine`, `test_backtest_engine` and related tests.

These tests depend on either `fakeredis` being installed or specific numeric precision packages. They fail in environments where those packages are absent.

**Fix:** Install missing packages per `backend/pyproject.toml` dev dependencies.

---

### 4. Wiring test `sys.modules` pollution

**Affected:** Tests that run after `test_shadow_wiring` or `test_alert_dispatcher_wiring` in the same pytest session.

Those two wiring tests patch `sys.modules` with `MagicMock` objects but do not fully restore the original state via `patch.dict` teardown. SQLAlchemy and other packages can end up in a broken state for subsequent tests.

**Workaround:** Run the affected test files in isolation:
```bash
pytest backend/tests/unit/test_shadow_wiring.py --noconftest --override-ini="addopts="
```

**Fix (TODO):** Replace `sys.modules` patching in both wiring tests with `unittest.mock.patch.dict(sys.modules, {...}, clear=False)` using a context manager so teardown is guaranteed.

---

## Design trade-offs

### 5. SCALPING/INTRADAY R:R vs RiskEngine minimum

**Documented in:** `agents/decision/constants.py` header

The decision layer uses strategy-specific R:R floors when generating `TradeCandidate`:
- SCALPING: 1.2
- INTRADAY: 1.5

The `RiskEngine` enforces a hard minimum of **2.0** on every candidate. This means `SCALPING` and `INTRADAY` candidates with R:R between their strategy floor and 2.0 will pass the decision layer but be rejected at Step 6 by the Risk Engine.

**Impact:** In practice, SCALPING and INTRADAY strategies are constrained to the same 2.0 R:R floor as TREND_FOLLOWING/BREAKOUT at execution. The strategy-specific floors only affect candidate generation pre-filtering, not final approval.

**Status:** Accepted design — CLAUDE.md mandates R:R ≥ 2.0 (absolute rule). The lower decision-layer floors are placeholders for future plan-level overrides. No action needed unless you intentionally want to support lower R:R for certain plans.

---

### 6. `OpenAIClient` lives in deprecated `agents/analyst/`

**Documented in:** `agents/analyst/__init__.py`

`OpenAIClient` is the only component from `agents/analyst/` still in active use — `ReviewerAgent` imports it. The rest of `agents/analyst/` (`AnalystAgent`, `build_user_prompt`, `parse_response`, etc.) is deprecated and no longer wired to the production pipeline.

**TODO:** Move `OpenAIClient` to `agents/common/openai_client.py`, update `ReviewerAgent` and `analysis_worker.py` imports, then retire `agents/analyst/` and its legacy tests.

---

### 7. ExecutionEngine dual-path re-validation for legacy flow

**Documented in:** Step 13 review

When `ExecutionRequest.approved_validation` is `None` (legacy path), `ExecutionEngine` calls `validate()` on the raw `RawSignal` internally. This path uses the old `RiskValidator.validate()` interface, not `validate_candidate()`. The new flow always provides `approved_validation`, so the legacy path is not triggered in the production pipeline.

**Status:** No action needed for the current production flow. The legacy path exists for backward compatibility during the transition period.
