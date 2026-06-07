import { z } from "zod"

// ── Auth ──────────────────────────────────────────────────────────────────────

export const userSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  display_name: z.string().optional().nullable(),
  plan: z.enum(["free", "pro", "elite"]),
  risk_profile: z.string().optional().nullable(),
  is_2fa_enabled: z.boolean(),
  is_onboarding_completed: z.boolean(),
  last_login_at: z.string().optional().nullable(),
})

export const loginResponseSchema = z.object({
  data: z.object({
    access_token: z.string(),
    token_type: z.literal("bearer"),
    expires_in: z.number(),
    user: userSchema,
  }),
})

// ── Positions ─────────────────────────────────────────────────────────────────

export const positionSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  coin: z.string(),
  direction: z.enum(["LONG", "SHORT"]),
  status: z.enum(["open", "closed"]),
  quantity: z.string(),
  entry_price: z.string(),
  current_price: z.string().optional().nullable(),
  take_profit: z.string(),
  stop_loss: z.string(),
  leverage: z.number(),
  margin_used: z.string(),
  unrealized_pnl: z.string().optional().nullable(),
  unrealized_pnl_pct: z.string().optional().nullable(),
  liquidation_price: z.string(),
  liquidation_distance_pct: z.string().optional().nullable(),
  tp_distance_pct: z.string().optional().nullable(),
  sl_distance_pct: z.string().optional().nullable(),
  duration_seconds: z.number().optional().nullable(),
  source: z.enum(["auto", "manual"]),
  signal_id: z.string().optional().nullable(),
  opened_at: z.string(),
})

export const positionsResponseSchema = z.object({
  data: z.object({
    positions: z.array(positionSchema),
    summary: z.object({
      total_positions: z.number(),
      total_unrealized_pnl: z.string(),
      total_margin_used: z.string(),
    }),
  }),
})

// ── Orders ────────────────────────────────────────────────────────────────────

export const orderSchema = z.object({
  id: z.string(),
  position_id: z.string().optional().nullable(),
  signal_id: z.string().optional().nullable(),
  symbol: z.string(),
  coin: z.string().optional(),
  order_type: z.enum(["market", "limit", "take_profit", "stop_loss"]),
  side: z.enum(["buy", "sell"]),
  quantity: z.string(),
  filled_quantity: z.string(),
  entry_price: z.string().optional().nullable(),
  filled_price: z.string().optional().nullable(),
  take_profit: z.string().optional().nullable(),
  stop_loss: z.string().optional().nullable(),
  leverage: z.number().optional().nullable(),
  fee: z.string(),
  status: z.enum(["pending", "filled", "cancelled", "rejected"]),
  source: z.enum(["auto", "manual"]),
  client_order_id: z.string(),
  exchange_order_id: z.string().optional().nullable(),
  created_at: z.string(),
  executed_at: z.string().optional().nullable(),
})

export const ordersResponseSchema = z.object({
  data: z.object({
    items: z.array(orderSchema),
    total: z.number(),
    limit: z.number(),
    offset: z.number(),
    has_next: z.boolean(),
  }),
})

// ── Stats ─────────────────────────────────────────────────────────────────────

export const dailyPnlSchema = z.object({
  date: z.string(),
  pnl: z.string(),
  pnl_pct: z.string(),
  cumulative_pnl: z.string(),
  trades: z.number(),
})

export const statsResponseSchema = z.object({
  data: z.object({
    period: z.string(),
    summary: z.object({
      total_pnl: z.string(),
      total_pnl_pct: z.string(),
      win_rate: z.string(),
      total_trades: z.number(),
      winning_trades: z.number(),
      losing_trades: z.number(),
      avg_win_pct: z.string(),
      avg_loss_pct: z.string(),
      max_drawdown: z.string(),
      sharpe_ratio: z.string(),
      profit_factor: z.string(),
    }),
    daily_pnl: z.array(dailyPnlSchema),
    best_trade: z
      .object({
        coin: z.string(),
        direction: z.enum(["LONG", "SHORT"]),
        pnl: z.string(),
        pnl_pct: z.string(),
        closed_at: z.string(),
      })
      .optional()
      .nullable(),
    worst_trade: z
      .object({
        coin: z.string(),
        direction: z.enum(["LONG", "SHORT"]),
        pnl: z.string(),
        pnl_pct: z.string(),
        closed_at: z.string(),
      })
      .optional()
      .nullable(),
  }),
})

// ── Binance Balance ───────────────────────────────────────────────────────────

export const accountBalanceSchema = z.object({
  data: z.object({
    total_balance: z.string(),
    available_balance: z.string(),
    total_unrealized_pnl: z.string(),
    today_pnl: z.string().optional().nullable(),
    today_pnl_pct: z.string().optional().nullable(),
  }),
})

// ── WebSocket events ──────────────────────────────────────────────────────────

export const wsAccountUpdatedSchema = z.object({
  type: z.literal("account.updated"),
  data: z.object({
    balance_usdt: z.string(),
    available_usdt: z.string(),
    total_unrealized_pnl: z.string(),
    today_pnl: z.string(),
    today_pnl_pct: z.string(),
  }),
  timestamp: z.string(),
})

export const wsPositionUpdatedSchema = z.object({
  type: z.literal("position.updated"),
  data: z.object({
    position_id: z.string(),
    coin: z.string(),
    current_price: z.string(),
    unrealized_pnl: z.string(),
    unrealized_pnl_pct: z.string(),
    liquidation_price: z.string(),
    liquidation_distance_pct: z.string(),
    tp_distance_pct: z.string(),
    sl_distance_pct: z.string(),
  }),
  timestamp: z.string(),
})

export const wsPositionWarningSchema = z.object({
  type: z.literal("position.warning"),
  data: z.object({
    position_id: z.string(),
    coin: z.string(),
    direction: z.enum(["LONG", "SHORT"]),
    warning_level: z.enum(["caution", "warning", "critical"]),
    liquidation_distance_pct: z.string(),
    current_price: z.string(),
    liquidation_price: z.string(),
    message: z.string(),
  }),
  timestamp: z.string(),
})

export const wsSignalNewSchema = z.object({
  type: z.literal("signal.new"),
  data: z.object({
    id: z.string(),
    coin: z.string(),
    direction: z.enum(["LONG", "SHORT", "HOLD"]),
    confidence: z.number(),
    entry_price: z.string(),
    take_profit: z.string(),
    stop_loss: z.string(),
    leverage: z.number(),
    rr_ratio: z.string(),
    reasons: z.array(z.string()),
    expires_at: z.string(),
  }),
  timestamp: z.string(),
})

// ── Inferred types ────────────────────────────────────────────────────────────

export type User = z.infer<typeof userSchema>
export type Position = z.infer<typeof positionSchema>
export type Order = z.infer<typeof orderSchema>
export type StatsData = z.infer<typeof statsResponseSchema>["data"]
export type DailyPnl = z.infer<typeof dailyPnlSchema>
export type AccountBalance = z.infer<typeof accountBalanceSchema>["data"]
export type WsAccountUpdated = z.infer<typeof wsAccountUpdatedSchema>
export type WsPositionUpdated = z.infer<typeof wsPositionUpdatedSchema>
export type WsPositionWarning = z.infer<typeof wsPositionWarningSchema>
export type WsSignalNew = z.infer<typeof wsSignalNewSchema>
