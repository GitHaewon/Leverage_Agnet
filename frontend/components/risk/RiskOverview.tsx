"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useStats, type StatsPeriod } from "@/hooks/useAccount"
import { cn, formatPrice } from "@/lib/utils"
import { TrendingUp, TrendingDown, AlertTriangle, Target } from "lucide-react"

const PERIODS: { label: string; value: StatsPeriod }[] = [
  { label: "7일", value: "7d" },
  { label: "30일", value: "30d" },
  { label: "90일", value: "90d" },
  { label: "전체", value: "all" },
]

interface StatRowProps {
  label: string
  value: string
  positive?: boolean | null
}

function StatRow({ label, value, positive = null }: StatRowProps) {
  const color =
    positive === null
      ? "text-foreground"
      : positive
        ? "text-green-400"
        : "text-red-400"
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn("text-sm font-medium tabular-nums", color)}>
        {value}
      </span>
    </div>
  )
}

export function RiskOverview() {
  const [period, setPeriod] = useState<StatsPeriod>("30d")
  const { data, isLoading, isError } = useStats(period)

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
        리스크 데이터 로딩 중...
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-red-400">
        데이터를 불러오지 못했습니다.
      </div>
    )
  }

  const s = data.summary
  const winRatePct = (parseFloat(s.win_rate) * 100).toFixed(1)
  const drawdown = parseFloat(s.max_drawdown)

  return (
    <div className="space-y-4">
      {/* Period selector */}
      <div className="flex gap-1">
        {PERIODS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => setPeriod(value)}
            className={cn(
              "rounded px-3 py-1 text-xs font-medium transition-colors",
              period === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Target className="h-4 w-4" />
              승률
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div
              className={cn(
                "text-2xl font-bold",
                parseFloat(s.win_rate) >= 0.6
                  ? "text-green-400"
                  : parseFloat(s.win_rate) >= 0.5
                    ? "text-yellow-400"
                    : "text-red-400"
              )}
            >
              {winRatePct}%
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {s.winning_trades}승 / {s.losing_trades}패 / 총 {s.total_trades}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
              최대 낙폭
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div
              className={cn(
                "text-2xl font-bold",
                drawdown > -5
                  ? "text-green-400"
                  : drawdown > -10
                    ? "text-yellow-400"
                    : "text-red-400"
              )}
            >
              {s.max_drawdown}%
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {drawdown > -5 ? "양호" : drawdown > -10 ? "주의" : "위험"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <TrendingUp className="h-4 w-4" />
              평균 수익
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-400">
              +{s.avg_win_pct}%
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              손익비 {s.profit_factor}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <TrendingDown className="h-4 w-4" />
              평균 손실
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-400">
              {s.avg_loss_pct}%
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              샤프 {s.sharpe_ratio}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Detailed stats */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">상세 통계</CardTitle>
        </CardHeader>
        <CardContent>
          <StatRow label="총 손익" value={formatPrice(s.total_pnl)} positive={parseFloat(s.total_pnl) >= 0} />
          <StatRow label="총 수익률" value={`${s.total_pnl_pct}%`} positive={parseFloat(s.total_pnl_pct) >= 0} />
          <StatRow label="총 거래 수" value={`${s.total_trades}건`} />
          <StatRow label="손익비 (Profit Factor)" value={s.profit_factor} positive={parseFloat(s.profit_factor) >= 2} />
          <StatRow label="샤프 지수" value={s.sharpe_ratio} positive={parseFloat(s.sharpe_ratio) >= 1} />
          <StatRow label="최대 낙폭" value={`${s.max_drawdown}%`} positive={false} />

          {data.best_trade && (
            <StatRow
              label="최고 거래"
              value={`${data.best_trade.coin} ${data.best_trade.direction} +${data.best_trade.pnl_pct}%`}
              positive={true}
            />
          )}
          {data.worst_trade && (
            <StatRow
              label="최악 거래"
              value={`${data.worst_trade.coin} ${data.worst_trade.direction} ${data.worst_trade.pnl_pct}%`}
              positive={false}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
