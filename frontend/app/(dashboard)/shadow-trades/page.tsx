"use client"

import { useState, useEffect, useCallback } from "react"
import { RefreshCw, FlaskConical } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ShadowStatsCards } from "@/components/shadow-trades/ShadowStatsCards"
import { ShadowTradesTable } from "@/components/shadow-trades/ShadowTradesTable"
import { OpenTradeCards } from "@/components/shadow-trades/OpenTradeCards"
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
      {/* 헤더 */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <FlaskConical className="h-6 w-6 text-primary" />
            Shadow Trading
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            실제 돈 없이 AI가 자동으로 거래를 시뮬레이션합니다. 30초마다 결과가 업데이트됩니다.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-muted-foreground">
              {lastUpdated.toLocaleTimeString("ko-KR")} 업데이트
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="gap-2"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            새로고침
          </Button>
        </div>
      </div>

      {/* 통계 카드 */}
      {loading && !stats ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6">
                <div className="h-8 w-24 animate-pulse rounded bg-muted" />
                <div className="mt-2 h-3 w-16 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : stats ? (
        <ShadowStatsCards stats={stats} />
      ) : null}

      {/* 진행중 포지션 */}
      {openTrades.length > 0 && <OpenTradeCards trades={openTrades} prices={prices} />}

      {/* 거래 내역 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-semibold">거래 내역</CardTitle>
            <div className="flex gap-1">
              {(["ALL", "OPEN", "TP_HIT", "SL_HIT"] as Filter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                    filter === f
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  {FILTER_LABELS[f]}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <ShadowTradesTable trades={trades} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
