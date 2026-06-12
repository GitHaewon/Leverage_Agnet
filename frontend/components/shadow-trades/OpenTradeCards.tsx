"use client"

import { ArrowUpCircle, ArrowDownCircle, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ShadowTrade } from "@/lib/schemas"

interface Props {
  trades: ShadowTrade[]
  prices: Record<string, number>
}

function ProgressBar({ current, tp, sl, direction }: {
  current: number | null
  tp: number
  sl: number
  direction: "LONG" | "SHORT"
}) {
  const range = Math.abs(tp - sl)
  if (range === 0) return null

  // 현재가 기준 진행률 (SL=0%, TP=100%)
  const pos = current !== null
    ? direction === "LONG"
      ? ((current - sl) / range) * 100
      : ((sl - current) / range) * 100
    : null

  const clamp = (v: number) => Math.min(Math.max(v, 0), 100)

  return (
    <div className="relative h-2 w-full rounded-full bg-muted">
      {/* TP 방향 채우기 */}
      {pos !== null && (
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-all ${pos >= 0 ? "bg-blue-500" : "bg-red-500"}`}
          style={{ width: `${clamp(pos)}%` }}
        />
      )}
      {/* SL 마커 */}
      <div className="absolute inset-y-0 left-0 w-0.5 bg-red-400" />
      {/* TP 마커 */}
      <div className="absolute inset-y-0 right-0 w-0.5 bg-green-400" />
      {/* 현재가 마커 */}
      {pos !== null && (
        <div
          className="absolute -top-1 h-4 w-0.5 bg-white"
          style={{ left: `${clamp(pos)}%` }}
        />
      )}
    </div>
  )
}

export function OpenTradeCards({ trades, prices }: Props) {
  if (trades.length === 0) return null

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin text-yellow-400" />
        진행 중인 포지션
        <span className="text-sm font-normal text-muted-foreground">({trades.length}건)</span>
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {trades.map((t) => {
          const entry = parseFloat(t.entry_price)
          const tp = parseFloat(t.tp_price)
          const sl = parseFloat(t.sl_price)
          const qty = parseFloat(t.quantity)
          const rrRatio = Math.abs(tp - entry) / Math.abs(entry - sl)
          const currentPrice = prices[t.coin] ?? null

          // 미실현 손익 계산
          const unrealizedPnl = currentPrice !== null
            ? t.direction === "LONG"
              ? (currentPrice - entry) * qty
              : (entry - currentPrice) * qty
            : null
          const pnlPct = unrealizedPnl !== null
            ? (unrealizedPnl / (entry * qty)) * 100
            : null
          const isPnlPositive = unrealizedPnl !== null && unrealizedPnl >= 0

          return (
            <Card key={String(t.id)} className="border-yellow-500/30">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between text-base">
                  <span className="font-bold">{t.coin}</span>
                  {t.direction === "LONG" ? (
                    <span className="flex items-center gap-1 text-blue-400">
                      <ArrowUpCircle className="h-4 w-4" />
                      LONG {t.leverage}x
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-red-400">
                      <ArrowDownCircle className="h-4 w-4" />
                      SHORT {t.leverage}x
                    </span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">

                {/* 현재가 + 미실현 손익 */}
                <div className="flex items-end justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">현재가</p>
                    <p className="text-xl font-bold">
                      {currentPrice !== null
                        ? `$${currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : "—"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">미실현 손익</p>
                    {unrealizedPnl !== null ? (
                      <p className={`text-lg font-semibold ${isPnlPositive ? "text-green-400" : "text-red-400"}`}>
                        {isPnlPositive ? "+" : ""}{unrealizedPnl.toFixed(2)} USDT
                        <span className="ml-1 text-xs">
                          ({isPnlPositive ? "+" : ""}{pnlPct!.toFixed(2)}%)
                        </span>
                      </p>
                    ) : (
                      <p className="text-sm text-muted-foreground">—</p>
                    )}
                  </div>
                </div>

                {/* 진행 바 (SL ~ 현재가 ~ TP) */}
                <ProgressBar current={currentPrice} tp={tp} sl={sl} direction={t.direction} />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span className="text-red-400">SL ${sl.toLocaleString()}</span>
                  <span className="text-green-400">TP ${tp.toLocaleString()}</span>
                </div>

                {/* 진입가 / R:R / 수량 */}
                <div className="flex justify-between text-xs text-muted-foreground border-t pt-2">
                  <span>진입가 ${entry.toLocaleString()}</span>
                  <span>R:R 1:{rrRatio.toFixed(1)}</span>
                  <span>수량 {qty.toFixed(4)}</span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
