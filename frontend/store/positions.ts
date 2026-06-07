import { create } from "zustand"
import type { Position, WsAccountUpdated, WsPositionUpdated } from "@/lib/schemas"

type LiveAccount = WsAccountUpdated["data"]

interface PositionsState {
  positions: Record<string, Position>
  liveAccount: LiveAccount | null
  setPositions: (positions: Position[]) => void
  applyPositionUpdate: (update: WsPositionUpdated["data"]) => void
  setLiveAccount: (data: LiveAccount) => void
  getOpenPositions: () => Position[]
}

export const usePositionsStore = create<PositionsState>()((set, get) => ({
  positions: {},
  liveAccount: null,

  setPositions: (positions) =>
    set({
      positions: Object.fromEntries(positions.map((p) => [p.id, p])),
    }),

  applyPositionUpdate: (update) =>
    set((state) => {
      const existing = state.positions[update.position_id]
      if (!existing) return state
      return {
        positions: {
          ...state.positions,
          [update.position_id]: {
            ...existing,
            current_price: update.current_price,
            unrealized_pnl: update.unrealized_pnl,
            unrealized_pnl_pct: update.unrealized_pnl_pct,
            liquidation_distance_pct: update.liquidation_distance_pct,
            tp_distance_pct: update.tp_distance_pct,
            sl_distance_pct: update.sl_distance_pct,
          },
        },
      }
    }),

  setLiveAccount: (data) => set({ liveAccount: data }),

  getOpenPositions: () =>
    Object.values(get().positions).filter((p) => p.status === "open"),
}))
