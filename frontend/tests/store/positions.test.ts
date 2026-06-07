/**
 * Zustand positions store tests.
 *
 * Verified:
 *   - setPositions: populates record by id
 *   - applyPositionUpdate: merges WS update fields
 *   - applyPositionUpdate: ignores unknown position_id
 *   - setLiveAccount: stores account balance
 *   - getOpenPositions: filters by status === "open"
 */

import { describe, it, expect, beforeEach } from "vitest"
import { usePositionsStore } from "@/store/positions"
import type { Position } from "@/lib/schemas"

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: "pos_01",
    symbol: "BTCUSDT",
    coin: "BTC",
    direction: "LONG",
    status: "open",
    quantity: "0.015",
    entry_price: "67452.00",
    current_price: "67890.00",
    take_profit: "69200.00",
    stop_loss: "66800.00",
    leverage: 5,
    margin_used: "202.36",
    unrealized_pnl: "+65.70",
    unrealized_pnl_pct: "+3.25",
    liquidation_price: "54250.00",
    liquidation_distance_pct: "20.09",
    tp_distance_pct: "1.93",
    sl_distance_pct: "-1.56",
    duration_seconds: 3625,
    source: "auto",
    signal_id: null,
    opened_at: "2026-06-04T08:29:20Z",
    ...overrides,
  }
}

function resetStore() {
  usePositionsStore.setState({ positions: {}, liveAccount: null })
}

describe("usePositionsStore", () => {
  beforeEach(resetStore)

  describe("setPositions", () => {
    it("stores positions indexed by id", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      expect(usePositionsStore.getState().positions["pos_01"]).toBeDefined()
    })

    it("replaces existing positions on reset", () => {
      usePositionsStore.getState().setPositions([makePosition({ id: "pos_01" })])
      usePositionsStore.getState().setPositions([makePosition({ id: "pos_02" })])
      const state = usePositionsStore.getState()
      expect(state.positions["pos_01"]).toBeUndefined()
      expect(state.positions["pos_02"]).toBeDefined()
    })

    it("handles empty array", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      usePositionsStore.getState().setPositions([])
      expect(Object.keys(usePositionsStore.getState().positions)).toHaveLength(0)
    })
  })

  describe("applyPositionUpdate", () => {
    it("merges current_price update", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      usePositionsStore.getState().applyPositionUpdate({
        position_id: "pos_01",
        coin: "BTC",
        current_price: "68000.00",
        unrealized_pnl: "+82.20",
        unrealized_pnl_pct: "+3.80",
        liquidation_price: "54250.00",
        liquidation_distance_pct: "20.29",
        tp_distance_pct: "1.76",
        sl_distance_pct: "-1.77",
      })
      expect(usePositionsStore.getState().positions["pos_01"]?.current_price).toBe("68000.00")
    })

    it("merges unrealized_pnl", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      usePositionsStore.getState().applyPositionUpdate({
        position_id: "pos_01",
        coin: "BTC",
        current_price: "68000.00",
        unrealized_pnl: "+82.20",
        unrealized_pnl_pct: "+3.80",
        liquidation_price: "54250.00",
        liquidation_distance_pct: "20.29",
        tp_distance_pct: "1.76",
        sl_distance_pct: "-1.77",
      })
      expect(usePositionsStore.getState().positions["pos_01"]?.unrealized_pnl).toBe("+82.20")
    })

    it("ignores unknown position_id", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      usePositionsStore.getState().applyPositionUpdate({
        position_id: "pos_unknown",
        coin: "BTC",
        current_price: "68000.00",
        unrealized_pnl: "+82.20",
        unrealized_pnl_pct: "+3.80",
        liquidation_price: "54250.00",
        liquidation_distance_pct: "20.29",
        tp_distance_pct: "1.76",
        sl_distance_pct: "-1.77",
      })
      expect(usePositionsStore.getState().positions["pos_01"]?.current_price).toBe("67890.00")
    })

    it("preserves other fields after update", () => {
      usePositionsStore.getState().setPositions([makePosition()])
      usePositionsStore.getState().applyPositionUpdate({
        position_id: "pos_01",
        coin: "BTC",
        current_price: "68000.00",
        unrealized_pnl: "+82.20",
        unrealized_pnl_pct: "+3.80",
        liquidation_price: "54250.00",
        liquidation_distance_pct: "20.29",
        tp_distance_pct: "1.76",
        sl_distance_pct: "-1.77",
      })
      const pos = usePositionsStore.getState().positions["pos_01"]
      expect(pos?.entry_price).toBe("67452.00")
      expect(pos?.leverage).toBe(5)
    })
  })

  describe("setLiveAccount", () => {
    it("stores account balance", () => {
      const account = {
        balance_usdt: "24157.85",
        available_usdt: "21342.60",
        total_unrealized_pnl: "+65.70",
        today_pnl: "+432.10",
        today_pnl_pct: "+1.82",
      }
      usePositionsStore.getState().setLiveAccount(account)
      expect(usePositionsStore.getState().liveAccount?.balance_usdt).toBe("24157.85")
    })
  })

  describe("getOpenPositions", () => {
    it("returns only open positions", () => {
      usePositionsStore.getState().setPositions([
        makePosition({ id: "pos_01", status: "open" }),
        makePosition({ id: "pos_02", status: "closed" }),
      ])
      const open = usePositionsStore.getState().getOpenPositions()
      expect(open).toHaveLength(1)
      expect(open[0]?.id).toBe("pos_01")
    })

    it("returns empty array when no open positions", () => {
      usePositionsStore.getState().setPositions([
        makePosition({ id: "pos_01", status: "closed" }),
      ])
      expect(usePositionsStore.getState().getOpenPositions()).toHaveLength(0)
    })
  })
})
