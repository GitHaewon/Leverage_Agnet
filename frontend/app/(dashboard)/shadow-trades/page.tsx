"use client"

import { useState, useEffect, useCallback } from "react"
import { RefreshCw, FlaskConical } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { ShadowStatsCards } from "@/components/shadow-trades/ShadowStatsCards"
import { ShadowTradesTable } from "@/components/shadow-trades/ShadowTradesTable"
import { OpenTradeCards, aggregateOpenTrades } from "@/components/shadow-trades/OpenTradeCards"
import { api } from "@/lib/api"
import { shadowTradesResponseSchema, shadowTradeStatsSchema } from "@/lib/schemas"
import type { ShadowTrade, ShadowTradeStats } from "@/lib/schemas"

type Filter = "ALL" | "OPEN" | "TP_HIT" | "SL_HIT"

const FILTER_LABELS: Record<Filter, string> = {
  ALL: "전체",
  OPEN: "진행중",
  TP_HIT: "목표 달성",
  SL_HIT: "손절",
}

export default function ShadowTradingPage() {
  const [stats, setStats] = useState<ShadowTradeStats | null>(null)
  const [trades, setTrades] = useState<ShadowTrade[]>([])
  const [openTrades, setOpenTrades] = useState<ShadowTrade[]>([])
  const [prices, setPrices] = useState<Record<string, number>>({})
  const [filter, setFilter] = useState<Filter>("ALL")
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const openPositions = aggregateOpenTrades(openTrades)

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [statsRes, tradesRes, openRes, pricesRes] = await Promise.all([
        api.get("/shadow-trades/stats"),
        api.get("/shadow-trades", {
          params: filter !== "ALL" ? { status: filter, limit: 100 } : { limit: 100 },
        }),
        api.get("/shadow-trades", { params: { status: "OPEN", limit: 50 } }),
        api.get("/shadow-trades/prices"),
      ])

      const parsedStats = shadowTradeStatsSchema.parse(statsRes.data)
      setStats(parsedStats.data)

      const parsedTrades = shadowTradesResponseSchema.parse(tradesRes.data)
      setTrades(parsedTrades.data.items)

      const parsedOpen = shadowTradesResponseSchema.parse(openRes.data)
      setOpenTrades(parsedOpen.data.items)

      setPrices((pricesRes.data as { data: Record<string, number> }).data ?? {})

      setLastUpdated(new Date())
    } catch {
      // API not yet authenticated or no data
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30_000)
    return () => clearInterval(interval)
  }, [fetchData])

  return (
    <div className="space-y-6">
      {/* 페이지 헤더 */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 mt-0.5">
            <FlaskConical className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              Shadow Trading
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground/60 max-w-md">
              실제 자금 없이 AI가 자동으로 거래를 시뮬레이션합니다. 30초마다 업데이트됩니다.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {lastUpdated && (
            <span className="text-xs tabular-nums text-muted-foreground/40">
              {lastUpdated.toLocaleTimeString("ko-KR")} 업데이트
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="gap-1.5 border-white/[0.08] bg-white/[0.03] text-muted-foreground hover:bg-white/[0.06] hover:text-foreground hover:border-white/[0.12] transition-all duration-200"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            새로고침
          </Button>
        </div>
      </div>

      {/* 통계 카드 스켈레톤 / 실제 카드 */}
      {loading && !stats ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 space-y-2">
                  <div className="h-2.5 w-14 animate-pulse rounded-md bg-white/[0.06]" />
                  <div className="h-7 w-20 animate-pulse rounded-md bg-white/[0.08]" />
                  <div className="h-2 w-10 animate-pulse rounded-md bg-white/[0.04]" />
                </div>
                <div className="h-9 w-9 flex-shrink-0 animate-pulse rounded-lg bg-white/[0.06]" />
              </div>
            </div>
          ))}
        </div>
      ) : stats ? (
        <ShadowStatsCards stats={stats} openPositionCount={openPositions.length} />
      ) : null}

      {/* 진행중 포지션 */}
      {openTrades.length > 0 && <OpenTradeCards trades={openTrades} prices={prices} />}

      {/* 거래 내역 */}
      <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.02] backdrop-blur-sm">
        {/* 테이블 헤더 영역 */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
          <h3 className="text-sm font-semibold text-foreground">거래 내역</h3>
          <div className="flex gap-0.5 rounded-lg bg-white/[0.04] p-1">
            {(["ALL", "OPEN", "TP_HIT", "SL_HIT"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition-all duration-200",
                  filter === f
                    ? "bg-white/[0.08] text-foreground shadow-sm"
                    : "text-muted-foreground/50 hover:text-muted-foreground"
                )}
              >
                {FILTER_LABELS[f]}
              </button>
            ))}
          </div>
        </div>

        {/* 테이블 본문 */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground/30" />
          </div>
        ) : (
          <ShadowTradesTable trades={trades} />
        )}
      </div>
    </div>
  )
}
