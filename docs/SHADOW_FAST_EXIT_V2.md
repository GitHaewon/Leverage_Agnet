# Shadow fast_exit_v2 experiment

This experiment is Shadow-only and opt-in. `baseline_v1` remains the control
and uses the existing approved candidate and RiskEngine sizing unchanged.

## Isolation

- Both flags default to `false`.
- `fast_exit_v2` is created as an immutable copy of the same source candidate.
- Both records share `signal_id` and `experiment_label`.
- Open risk is aggregated in separate strategy ledgers. The shared pipeline
  sees baseline/legacy positions only.
- Live `ExecutionEngine` rejects `strategy_version=fast_exit_v2`.

## Exit policy

The missing Stage 6 correction text did not provide calibrated numbers. The
following values are therefore **[ASSUMPTION] configurable defaults**:

- TP distance: `entry × 0.006`
- SL distance: `entry × max(0.003, min_sl_pct)`
- Minimum R:R: `2.0`
- Maximum holding time: `900` seconds
- Expected TP net profit must remain positive and meet the configured
  cost-profit multiple.

TP and SL are rounded to the symbol tick in a conservative executable
direction. Invalid direction, R:R, cost gate or exchange rules produce a
structured rejected experiment record without rejecting baseline.

## Risk sizing

```text
risk_budget = equity × risk_per_trade_pct

worst_loss_per_coin =
    abs(entry - stop)
    + entry taker fee
    + stop-fill taker fee
    + entry slippage
    + stop-fill slippage
    + conservative funding cost

raw_quantity = risk_budget / worst_loss_per_coin
quantity = floor_to_lot_step(raw_quantity)
```

The minimum leverage satisfying the margin cap is selected. Confidence, score
and estimated win rate are not inputs. If the leverage cap is insufficient,
quantity is reduced once to the cap and every invariant is recalculated.

Required invariant:

```text
actual_max_loss <= risk_budget
```

## Funding

Sizing never counts a possible funding credit. If the next funding timestamp is
not available, at least one interval is charged as a conservative **[ASSUMPTION]**
fallback. Actual Shadow PnL uses known UTC interval boundaries.

## Supported rules

BTCUSDT and ETHUSDT use the repository's existing quantity/min-notional rules.
Price ticks are **[ASSUMPTION]** until Binance `exchangeInfo` is persisted.
Unknown symbols are rejected with `UNSUPPORTED_SYMBOL_RULES`; they never inherit
BTC defaults.

## Rollout and rollback

1. Apply migrations through revision `026`.
2. Keep both feature flags false and run baseline regression tests.
3. Enable `SHADOW_FAST_EXIT_V2_ENABLED` in Shadow only.
4. Enable `SHADOW_RISK_SIZING_V2_ENABLED` after verifying dual records and loss
   restoration.
5. Roll back instantly by setting both flags to false. Existing experimental
   rows remain queryable; baseline behavior returns to the prior path.
6. Database rollback, if required after code rollback, is `alembic downgrade
   025`.
