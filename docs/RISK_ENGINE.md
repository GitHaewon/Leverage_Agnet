# Risk Engine

> Updated: 2026-06-12
> Source: `agents/risk/engine.py`, `agents/risk/constants.py`, `agents/decision/constants.py`

---

## Role in the pipeline

`RiskEngine.validate_candidate()` is the **final safety gate** before Portfolio → PositionManager → Execution. It runs at Step 6 of the 10-step pipeline after the AI review. No order reaches execution without passing this gate.

The gate is intentionally duplicated with certain checks in `decide_final_action()` (Step 7). This duplication is deliberate defense-in-depth and must not be removed.

---

## Checks performed by `validate_candidate`

| Check | Condition for rejection | Error code |
|---|---|---|
| Stop-loss present | `stop_loss is None` | `ORDER_003` |
| Take-profit present | `take_profit is None` | `TP_MISSING` |
| Minimum R:R | `actual_rr < 2.0` | `LOW_RR` |
| Liquidation distance | `entry` too close to `liquidation_price` | `LIQ_DISTANCE` |
| Spread limit | `spread_bps > DECISION_MAX_SPREAD_BPS` | `HIGH_SPREAD` |
| Slippage limit | `slippage_bps > DECISION_MAX_SLIPPAGE_BPS` | `HIGH_SLIPPAGE` |
| Expected net profit | `expected_net_profit < MIN_EXPECTED_NET_PROFIT_PCT × notional` | `NET_PROFIT` |
| Daily loss limit | `daily_loss_usdt ≥ user.daily_loss_limit` | `DAILY_LOSS` |
| Weekly loss limit | `weekly_loss_usdt ≥ weekly_limit_usdt` | `WEEKLY_LOSS` |
| Kill switch | `kill_switch_active = True` | `KILL_SWITCH` |
| Consecutive losses | `consecutive_losses ≥ DECISION_MAX_CONSECUTIVE_LOSSES` | `CONSEC_LOSS` |
| Open positions | `open_positions_count ≥ DECISION_MAX_OPEN_POSITIONS` | `MAX_POSITIONS` |
| Withdrawal permission | API key has withdrawal permission | `WITHDRAW_PERM` |

---

## Hard limits (non-configurable)

These match CLAUDE.md absolute rules and require CTO approval to change:

```python
REQUIRE_STOP_LOSS      = True   # No SL → no order, ever
REQUIRE_TAKE_PROFIT    = True   # No TP → no order
REDUCE_ONLY_EXIT_ORDERS = True  # TP/SL are always reduce-only
CLOSE_IF_SL_TP_FAIL    = True   # TP/SL failure → emergency market close
ISOLATED_MARGIN_ONLY   = True   # Cross margin prohibited
```

---

## Position sizing formula

```python
# From CLAUDE.md §포지션 사이징 공식
risk_amount = account_balance × risk_per_trade_pct
size        = risk_amount / abs(entry - stop_loss)
quantity    = (size × leverage) / entry_price
leverage    = min(signal.leverage, user.max_leverage, 20)
```

---

## Kill switch and daily loss auto-stop

When `daily_loss_usdt ≥ user.daily_loss_limit`:
1. `validate_candidate` rejects with `DAILY_LOSS`
2. `disable_auto_trading(user_id)` is called
3. Telegram alert is dispatched: "일일 손실 한도 도달 — 자동매매 중단"

Similarly for weekly loss and consecutive losses. The auto-stop cannot be bypassed by retrying; a manual re-enable action is required.

---

## Emergency TP/SL handling

When a market entry order fills but the TP or SL order fails:

```
1. Retry TP/SL placement once
2. If retry fails → execute emergency market close at current price
3. Compute realized PnL from actual fill price
4. Deduct realized PnL from daily/weekly loss counters
5. Dispatch Telegram alert: "긴급 청산 완료"
6. Call post_trade_hook with EMERGENCY_CLOSED status
```

This ensures no position is left open without stop-loss protection.

---

## Validation result

`agents/risk/models.py` `ValidationResult`

```python
@dataclass
class ValidationResult:
    approved:         bool
    rejection_code:   str | None
    rejection_reason: str | None
    quantity:         Decimal        # final quantity after sizing
    final_leverage:   int            # capped leverage
    warnings:         list[str]
```

The pipeline wraps this into `RiskCheckResult` (`agents/decision/models.py`) for the `FinalDecision` container.
