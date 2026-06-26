"use client"

import { TrendingUp, TrendingDown, Activity } from "lucide-react"
import type { ShadowTrade } from "@/lib/schemas"
import { cn } from "@/lib/utils"

interface Props {
  trades: ShadowTrade[]
  prices: Record<string, number>
}

export function aggregateOpenTrades(trades: ShadowTrade[]): ShadowTrade[] {
  const grouped = new Map<string, ShadowTrade[]>()

  for (const trade of trades) {
    const key = `${trade.symbol}:${trade.direction}`
    const existing = grouped.get(key)
    if (existing) existing.push(trade)
    else grouped.set(key, [trade])
  }

  return Array.from(grouped.values()).map((legs) => {
    if (legs.length === 1) return legs[0]

    const totalQty = legs.reduce((sum, leg) => sum + parseFloat(leg.quantity), 0)
    const weighted = (field: "entry_price" | "tp_price" | "sl_price") => {
      if (totalQty === 0) return parseFloat(legs[0][field])
      return (
        legs.reduce(
          (sum, leg) => sum + parseFloat(leg[field]) * parseFloat(leg.quantity),
          0,
        ) / totalQty
      )
    }
    const weightedLeverage =
      totalQty === 0
        ? legs[0].leverage
        : legs.reduce((sum, leg) => sum + leg.leverage * parseFloat(leg.quantity), 0) /
          totalQty
    const openedAt = legs
      .map((leg) => leg.opened_at)
      .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0]

    return {
      ...legs[0],
      id: legs.map((leg) => leg.id).join(":"),
      entry_price: String(weighted("entry_price")),
      tp_price: String(weighted("tp_price")),
      sl_price: String(weighted("sl_price")),
      quantity: String(totalQty),
      leverage: Math.round(weightedLeverage),
      opened_at: openedAt,
    }
  })
}

function formatPrice(value: number) {
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function ProgressBar({
  current,
  tp,
  sl,
  direction,
}: {
  current: number | null
  tp: number
  sl: number
  direction: "LONG" | "SHORT"
}) {
  const range = Math.abs(tp - sl)
  if (range === 0) return null

  const pos =
    current !== null
      ? direction === "LONG"
        ? ((current - sl) / range) * 100
        : ((sl - current) / range) * 100
      : null
  const clamp = (v: number) => Math.min(Math.max(v, 0), 100)
  const clamped = pos !== null ? clamp(pos) : 0
  const isProfit = pos !== null && pos >= 50

  return (
    <div className="space-y-1.5">
      <div className="relative h-1.5 w-full rounded-full bg-white/[0.06]">
        {/* Fill bar */}
        {pos !== null && (
          <div
            className={cn(
              "absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out",
              isProfit ? "bg-emerald-500" : "bg-rose-500"
            )}
            style={{ width: `${clamped}%` }}
          />
        )}
        {/* SL marker */}
        <div className="absolute inset-y-[-3px] left-0 w-0.5 rounded-full bg-rose-500/50" />
        {/* TP marker */}
        <div className="absolute inset-y-[-3px] right-0 w-0.5 rounded-full bg-emerald-500/50" />
        {/* Current price pin */}
        {pos !== null && (
          <div
            className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white shadow-[0_0_6px_rgba(255,255,255,0.5)]"
            style={{ left: `${clamped}%` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[10px] font-medium tabular-nums">
        <span className="text-rose-400/80">SL {formatPrice(sl)}</span>
        <span className="text-emerald-400/80">TP {formatPrice(tp)}</span>
      </div>
    </div>
  )
}

export function OpenTradeCards({ trades, prices }: Props) {
  const positions = aggregateOpenTrades(trades)

  if (positions.length === 0) return null

  return (
    <div>
      {/* Section header */}
      <div className="mb-4 flex items-center gap-2.5">
        <Activity className="h-4 w-4 text-amber-400 animate-pulse" />
        <h2 className="text-sm font-semibold text-foreground">진행 중인 포지션</h2>
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-400">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse-dot" />
          {positions.length}개 활성
        </span>
        <span className="text-xs text-muted-foreground/40">/ 체결 {trades.length}건</span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {positions.map((t) => {
          const entry = parseFloat(t.entry_price)
          const tp = parseFloat(t.tp_price)
          const sl = parseFloat(t.sl_price)
          const qty = parseFloat(t.quantity)
          const risk = Math.abs(entry - sl)
          const rrRatio = risk === 0 ? 0 : Math.abs(tp - entry) / risk
          const currentPrice = prices[t.coin] ?? null
          const unrealizedPnl =
            currentPrice !== null
              ? t.direction === "LONG"
                ? (currentPrice - entry) * qty
                : (entry - currentPrice) * qty
              : null
          const notional = entry * qty
          const pnlPct =
            unrealizedPnl !== null && notional !== 0
              ? (unrealizedPnl / notional) * 100
              : null
          const isPnlPositive = unrealizedPnl !== null && unrealizedPnl >= 0
          const isLong = t.direction === "LONG"

          return (
            <div
              key={String(t.id)}
              className={cn(
                "relative overflow-hidden rounded-xl border p-4 backdrop-blur-sm transition-all duration-200",
                "hover:shadow-[0_8px_32px_rgba(0,0,0,0.4)] hover:-translate-y-0.5",
                isLong
                  ? "border-blue-500/20 bg-blue-500/[0.03] hover:border-blue-500/30"
                  : "border-rose-500/20 bg-rose-500/[0.03] hover:border-rose-500/30"
              )}
            >
              {/* Subtle corner accent */}
              <div
                className={cn(
                  "pointer-events-none absolute -right-8 -top-8 h-20 w-20 rounded-full blur-2xl opacity-20",
                  isLong ? "bg-blue-500" : "bg-rose-500"
                )}
              />

              {/* Card header: coin + direction + status */}
              <div className="relative flex items-start justify-between mb-4">
                <div className="flex items-center gap-2.5">
                  <span className="text-2xl font-bold tracking-tight text-foreground">
                    {t.coin}
                  </span>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-bold",
                      isLong
                        ? "bg-blue-500/10 border-blue-500/25 text-blue-400"
                        : "bg-rose-500/10 border-rose-500/25 text-rose-400"
                    )}
                  >
                    {isLong ? (
                      <TrendingUp className="h-3 w-3" />
                    ) : (
                      <TrendingDown className="h-3 w-3" />
                    )}
                    {t.direction} {t.leverage}x
                  </span>
                </div>
                <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400">
                  <span className="h-1 w-1 rounded-full bg-amber-400 animate-pulse-dot" />
                  진행중
                </span>
              </div>

              {/* Current price + Unrealized PnL */}
              <div className="relative flex items-end justify-between mb-4">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/50 mb-1">
                    현재가
                  </p>
                  <p className="text-xl font-bold tabular-nums text-foreground">
                    {currentPrice !== null ? formatPrice(currentPrice) : "—"}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/50 mb-1">
                    미실현 손익
                  </p>
                  {unrealizedPnl !== null ? (
                    <div>
                      <p
                        className={cn(
                          "text-xl font-bold tabular-nums",
                          isPnlPositive ? "text-emerald-400" : "text-rose-400"
                        )}
                      >
                        {isPnlPositive ? "+" : ""}
                        {unrealizedPnl.toFixed(2)}
                        <span className="ml-0.5 text-xs font-medium opacity-60">USDT</span>
                      </p>
                      {pnlPct !== null && (
                        <p
                          className={cn(
                            "text-[11px] font-medium tabular-nums",
                            isPnlPositive ? "text-emerald-400/60" : "text-rose-400/60"
                          )}
                        >
                          {isPnlPositive ? "+" : ""}
                          {pnlPct.toFixed(2)}%
                        </p>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground/30">—</p>
                  )}
                </div>
              </div>

              {/* Progress bar */}
              <ProgressBar
                current={currentPrice}
                tp={tp}
                sl={sl}
                direction={t.direction}
              />

              {/* Details row */}
              <div className="mt-3 grid grid-cols-3 gap-2 border-t border-white/[0.05] pt-3">
                <div>
                  <p className="text-[10px] text-muted-foreground/50 mb-0.5">평단가</p>
                  <p className="text-xs font-semibold tabular-nums text-foreground/70">
                    {formatPrice(entry)}
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] text-muted-foreground/50 mb-0.5">R:R</p>
                  <span
                    className={cn(
                      "inline-block rounded px-1.5 py-0.5 text-xs font-bold",
                      rrRatio >= 2
                        ? "bg-emerald-500/10 text-emerald-400"
                        : "bg-amber-500/10 text-amber-400"
                    )}
                  >
                    1:{rrRatio.toFixed(1)}
                  </span>
                </div>
                <div className="text-right">
                  <p className="text-[10px] text-muted-foreground/50 mb-0.5">수량</p>
                  <p className="text-xs font-semibold tabular-nums text-foreground/70">
                    {qty.toFixed(4)}
                  </p>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
