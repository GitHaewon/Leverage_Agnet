/**
 * Zod schema validation tests.
 *
 * Verified:
 *   - loginResponseSchema: valid / missing field / wrong enum
 *   - positionSchema: LONG + HOLD rejection / partial fields
 *   - positionsResponseSchema: full parse
 *   - ordersResponseSchema: items array
 *   - statsResponseSchema: summary + daily_pnl
 *   - accountBalanceSchema: optional today_pnl
 *   - WS schemas: account.updated, position.updated, signal.new type discrimination
 */

import { describe, it, expect } from "vitest"
import {
  loginResponseSchema,
  positionSchema,
  positionsResponseSchema,
  ordersResponseSchema,
  statsResponseSchema,
  accountBalanceSchema,
  wsAccountUpdatedSchema,
  wsPositionUpdatedSchema,
  wsSignalNewSchema,
} from "@/lib/schemas"

// ── helpers ───────────────────────────────────────────────────────────────────

function makeUser() {
  return {
    id: "550e8400-e29b-41d4-a716-446655440000",
    email: "user@example.com",
    display_name: "김지민",
    plan: "pro",
    risk_profile: "moderate",
    is_2fa_enabled: true,
    is_onboarding_completed: true,
  }
}

function makePosition(overrides: Record<string, unknown> = {}) {
  return {
    id: "pos_01",
    symbol: "BTCUSDT",
    coin: "BTC",
    direction: "LONG",
    status: "open",
    quantity: "0.015",
    entry_price: "67452.00",
    take_profit: "69200.00",
    stop_loss: "66800.00",
    leverage: 5,
    margin_used: "202.36",
    liquidation_price: "54250.00",
    source: "auto",
    opened_at: "2026-06-04T08:29:20Z",
    ...overrides,
  }
}

// ── loginResponseSchema ───────────────────────────────────────────────────────

describe("loginResponseSchema", () => {
  it("parses valid login response", () => {
    const raw = {
      data: {
        access_token: "tok123",
        token_type: "bearer",
        expires_in: 900,
        user: makeUser(),
      },
    }
    const result = loginResponseSchema.parse(raw)
    expect(result.data.access_token).toBe("tok123")
    expect(result.data.user.plan).toBe("pro")
  })

  it("rejects missing access_token", () => {
    const raw = { data: { token_type: "bearer", expires_in: 900, user: makeUser() } }
    expect(() => loginResponseSchema.parse(raw)).toThrow()
  })

  it("rejects invalid plan enum", () => {
    const raw = {
      data: {
        access_token: "tok",
        token_type: "bearer",
        expires_in: 900,
        user: { ...makeUser(), plan: "ultra" },
      },
    }
    expect(() => loginResponseSchema.parse(raw)).toThrow()
  })

  it("rejects wrong token_type", () => {
    const raw = {
      data: {
        access_token: "tok",
        token_type: "jwt",
        expires_in: 900,
        user: makeUser(),
      },
    }
    expect(() => loginResponseSchema.parse(raw)).toThrow()
  })
})

// ── positionSchema ─────────────────────────────────────────────────────────────

describe("positionSchema", () => {
  it("parses LONG position", () => {
    const result = positionSchema.parse(makePosition())
    expect(result.direction).toBe("LONG")
    expect(result.leverage).toBe(5)
  })

  it("parses SHORT position", () => {
    const result = positionSchema.parse(makePosition({ direction: "SHORT" }))
    expect(result.direction).toBe("SHORT")
  })

  it("parses optional unrealized_pnl as null", () => {
    const result = positionSchema.parse(makePosition({ unrealized_pnl: null }))
    expect(result.unrealized_pnl).toBeNull()
  })

  it("rejects invalid direction", () => {
    expect(() => positionSchema.parse(makePosition({ direction: "HOLD" }))).toThrow()
  })

  it("parses optional current_price", () => {
    const result = positionSchema.parse(makePosition({ current_price: "67890.00" }))
    expect(result.current_price).toBe("67890.00")
  })

  it("accepts auto source", () => {
    const result = positionSchema.parse(makePosition({ source: "auto" }))
    expect(result.source).toBe("auto")
  })

  it("accepts manual source", () => {
    const result = positionSchema.parse(makePosition({ source: "manual" }))
    expect(result.source).toBe("manual")
  })
})

// ── positionsResponseSchema ────────────────────────────────────────────────────

describe("positionsResponseSchema", () => {
  it("parses positions list with summary", () => {
    const raw = {
      data: {
        positions: [makePosition()],
        summary: {
          total_positions: 1,
          total_unrealized_pnl: "+65.70",
          total_margin_used: "202.36",
        },
      },
    }
    const result = positionsResponseSchema.parse(raw)
    expect(result.data.positions).toHaveLength(1)
    expect(result.data.summary.total_positions).toBe(1)
  })

  it("parses empty positions list", () => {
    const raw = {
      data: {
        positions: [],
        summary: { total_positions: 0, total_unrealized_pnl: "0", total_margin_used: "0" },
      },
    }
    const result = positionsResponseSchema.parse(raw)
    expect(result.data.positions).toHaveLength(0)
  })
})

// ── ordersResponseSchema ───────────────────────────────────────────────────────

describe("ordersResponseSchema", () => {
  it("parses orders list with pagination", () => {
    const raw = {
      data: {
        items: [
          {
            id: "ord_01",
            symbol: "BTCUSDT",
            order_type: "market",
            side: "buy",
            quantity: "0.015",
            filled_quantity: "0.015",
            fee: "2.02",
            status: "filled",
            source: "auto",
            client_order_id: "tc_01",
            created_at: "2026-06-04T08:29:15Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_next: false,
      },
    }
    const result = ordersResponseSchema.parse(raw)
    expect(result.data.items).toHaveLength(1)
    expect(result.data.has_next).toBe(false)
  })

  it("rejects invalid order status", () => {
    const raw = {
      data: {
        items: [
          {
            id: "ord_01",
            symbol: "BTCUSDT",
            order_type: "market",
            side: "buy",
            quantity: "0.015",
            filled_quantity: "0.015",
            fee: "2.02",
            status: "unknown_status",
            source: "auto",
            client_order_id: "tc_01",
            created_at: "2026-06-04T08:29:15Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_next: false,
      },
    }
    expect(() => ordersResponseSchema.parse(raw)).toThrow()
  })
})

// ── statsResponseSchema ────────────────────────────────────────────────────────

describe("statsResponseSchema", () => {
  it("parses stats response", () => {
    const raw = {
      data: {
        period: "30d",
        summary: {
          total_pnl: "1234.56",
          total_pnl_pct: "5.14",
          win_rate: "0.67",
          total_trades: 42,
          winning_trades: 28,
          losing_trades: 14,
          avg_win_pct: "3.21",
          avg_loss_pct: "-1.08",
          max_drawdown: "-2.34",
          sharpe_ratio: "1.87",
          profit_factor: "2.32",
        },
        daily_pnl: [
          { date: "2026-05-05", pnl: "234.50", pnl_pct: "0.98", cumulative_pnl: "234.50", trades: 3 },
        ],
      },
    }
    const result = statsResponseSchema.parse(raw)
    expect(result.data.summary.total_trades).toBe(42)
    expect(result.data.daily_pnl).toHaveLength(1)
  })

  it("parses null best_trade / worst_trade", () => {
    const raw = {
      data: {
        period: "7d",
        summary: {
          total_pnl: "0",
          total_pnl_pct: "0",
          win_rate: "0",
          total_trades: 0,
          winning_trades: 0,
          losing_trades: 0,
          avg_win_pct: "0",
          avg_loss_pct: "0",
          max_drawdown: "0",
          sharpe_ratio: "0",
          profit_factor: "0",
        },
        daily_pnl: [],
        best_trade: null,
        worst_trade: null,
      },
    }
    const result = statsResponseSchema.parse(raw)
    expect(result.data.best_trade).toBeNull()
  })
})

// ── accountBalanceSchema ───────────────────────────────────────────────────────

describe("accountBalanceSchema", () => {
  it("parses balance response", () => {
    const raw = {
      data: {
        total_balance: "24500.00",
        available_balance: "21342.60",
        total_unrealized_pnl: "+342.15",
      },
    }
    const result = accountBalanceSchema.parse(raw)
    expect(result.data.total_balance).toBe("24500.00")
    expect(result.data.today_pnl).toBeUndefined()
  })

  it("parses optional today_pnl when present", () => {
    const raw = {
      data: {
        total_balance: "24500.00",
        available_balance: "21342.60",
        total_unrealized_pnl: "+342.15",
        today_pnl: "+432.10",
        today_pnl_pct: "+1.82",
      },
    }
    const result = accountBalanceSchema.parse(raw)
    expect(result.data.today_pnl).toBe("+432.10")
  })
})

// ── WebSocket schemas ──────────────────────────────────────────────────────────

describe("wsAccountUpdatedSchema", () => {
  it("parses account.updated event", () => {
    const raw = {
      type: "account.updated",
      data: {
        balance_usdt: "24157.85",
        available_usdt: "21342.60",
        total_unrealized_pnl: "+65.70",
        today_pnl: "+432.10",
        today_pnl_pct: "+1.82",
      },
      timestamp: "2026-06-04T09:30:00Z",
    }
    const result = wsAccountUpdatedSchema.parse(raw)
    expect(result.data.balance_usdt).toBe("24157.85")
  })

  it("rejects wrong type literal", () => {
    const raw = { type: "position.updated", data: {}, timestamp: "" }
    expect(() => wsAccountUpdatedSchema.parse(raw)).toThrow()
  })
})

describe("wsPositionUpdatedSchema", () => {
  it("parses position.updated event", () => {
    const raw = {
      type: "position.updated",
      data: {
        position_id: "pos_01",
        coin: "BTC",
        current_price: "67890.00",
        unrealized_pnl: "+65.70",
        unrealized_pnl_pct: "+3.25",
        liquidation_price: "54250.00",
        liquidation_distance_pct: "20.09",
        tp_distance_pct: "1.93",
        sl_distance_pct: "-1.56",
      },
      timestamp: "2026-06-04T09:30:01Z",
    }
    const result = wsPositionUpdatedSchema.parse(raw)
    expect(result.data.position_id).toBe("pos_01")
  })
})

describe("wsSignalNewSchema", () => {
  it("parses signal.new event", () => {
    const raw = {
      type: "signal.new",
      data: {
        id: "sig_01",
        coin: "BTC",
        direction: "LONG",
        confidence: 0.87,
        entry_price: "67450.00",
        take_profit: "69200.00",
        stop_loss: "66800.00",
        leverage: 5,
        rr_ratio: "2.71",
        reasons: ["RSI 42 과매도"],
        expires_at: "2026-06-04T10:30:00Z",
      },
      timestamp: "2026-06-04T09:30:00Z",
    }
    const result = wsSignalNewSchema.parse(raw)
    expect(result.data.confidence).toBe(0.87)
    expect(result.data.direction).toBe("LONG")
  })

  it("rejects invalid direction", () => {
    const raw = {
      type: "signal.new",
      data: {
        id: "sig_01",
        coin: "BTC",
        direction: "BUY",
        confidence: 0.87,
        entry_price: "67450.00",
        take_profit: "69200.00",
        stop_loss: "66800.00",
        leverage: 5,
        rr_ratio: "2.71",
        reasons: [],
        expires_at: "2026-06-04T10:30:00Z",
      },
      timestamp: "2026-06-04T09:30:00Z",
    }
    expect(() => wsSignalNewSchema.parse(raw)).toThrow()
  })
})
